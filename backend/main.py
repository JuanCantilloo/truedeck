import os
import io
import json
import datetime
import logging
import shutil
import tempfile
import time
import uuid
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, Query, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, or_

from database import init_db, get_db, SessionLocal
from models import RegistroTelemetria, ArchivoCargado
from parser import parse_excel_or_csv_fast, iter_csv_telemetry_batches

app = FastAPI(title="TrueDeck Telemetría & Mapas API", version="1.0.0")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
UPLOAD_CHUNK_DIR = os.path.join(tempfile.gettempdir(), "truedeck-upload-chunks")
UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
logger = logging.getLogger(__name__)

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def read_root():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "TrueDeck API is running"}

# Enable CORS for frontend Vite dev server and production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.datetime.utcnow().isoformat()}

@app.get("/api/stats-resumen")
def stats_resumen(db: Session = Depends(get_db)):
    total_registros = db.query(func.count(RegistroTelemetria.id)).scalar() or 0
    total_fallas = db.query(func.count(RegistroTelemetria.id)).filter(
        RegistroTelemetria.tramaRetransmitida == True
    ).scalar() or 0
    total_vehiculos = db.query(func.count(func.distinct(RegistroTelemetria.idVehiculo))).scalar() or 0
    total_archivos = db.query(func.count(ArchivoCargado.id)).scalar() or 0
    
    tasa_falla = round((total_fallas / total_registros * 100), 2) if total_registros > 0 else 0.0

    return {
        "totalRegistros": total_registros,
        "totalConFalla": total_fallas,
        "totalVehiculos": total_vehiculos,
        "totalArchivos": total_archivos,
        "tasaFallaPorcentaje": tasa_falla
    }

@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    buses: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    filename = os.path.basename(file.filename or "archivo.xlsx")
    contents = await file.read()
    selected_buses = _parse_selected_buses(buses)
    return await run_in_threadpool(
        _import_telemetry_file, io.BytesIO(contents), filename, selected_buses, db
    )

def _parse_selected_buses(buses: Optional[str]) -> List[str]:
    if not buses:
        return []
    try:
        parsed = json.loads(buses)
    except json.JSONDecodeError:
        parsed = buses.split(',')
    if isinstance(parsed, str):
        parsed = parsed.split(',')
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="La selección de buses no es válida.")
    return [str(item).strip() for item in parsed if str(item).strip()]


def _import_telemetry_file(content, filename: str, selected_buses: List[str], db: Session):
    raw_conn = db.connection().connection
    cursor = raw_conn.cursor()
    total_registros = 0
    fallas_count = 0
    try:
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        insert_sql = """
            INSERT INTO telemetria (
                idRuta, idVehiculo, fechaHoraLecturaDato, fechaHoraEnvioDato,
                latitud, longitud, tipoBus, RangoLatencia, tramaRetransmitida,
                velocidadVehiculo, aceleracionVehiculo, latenciaMinutos,
                archivoOrigen, fechaCarga
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

        if filename.lower().endswith('.csv') and isinstance(content, str):
            batches = iter_csv_telemetry_batches(content, filename, selected_buses)
        else:
            parsed = parse_excel_or_csv_fast(content, filename, selected_buses)
            batches = [parsed]

        for tuples_data, batch_rows, batch_failures in batches:
            if tuples_data:
                cursor.executemany(insert_sql, tuples_data)
            total_registros += batch_rows
            fallas_count += batch_failures

        if total_registros == 0:
            raw_conn.rollback()
            raise HTTPException(status_code=400, detail="El archivo no contiene registros válidos para la selección indicada.")

        cursor.execute(
            """
            INSERT INTO archivos_cargados (nombre, totalRegistros, totalConFalla, fechaCarga)
            VALUES (?, ?, ?, ?)
            """,
            (filename, total_registros, fallas_count, datetime.datetime.utcnow().isoformat())
        )
        raw_conn.commit()
    except (ValueError, OSError) as e:
        raw_conn.rollback()
        raise HTTPException(status_code=400, detail=f"Error al procesar archivo: {str(e)}")
    except HTTPException:
        raw_conn.rollback()
        raise
    except Exception as e:
        raw_conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar registros en base de datos: {str(e)}")

    return {
        "success": True,
        "filename": filename,
        "registrosImportados": total_registros,
        "totalConFalla": fallas_count,
        "busesSeleccionados": selected_buses,
    }


def _upload_session_dir(upload_id: str) -> str:
    try:
        safe_id = str(uuid.UUID(upload_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Identificador de carga inválido.")
    return os.path.join(UPLOAD_CHUNK_DIR, safe_id)


def _remove_upload_session(upload_dir: str) -> None:
    try:
        shutil.rmtree(upload_dir)
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("Could not remove temporary upload directory %s", upload_dir)


def _cleanup_stale_upload_sessions() -> None:
    if not os.path.isdir(UPLOAD_CHUNK_DIR):
        return
    cutoff = time.time() - 24 * 60 * 60
    try:
        entries = list(os.scandir(UPLOAD_CHUNK_DIR))
    except OSError:
        logger.exception("Could not inspect temporary upload directory")
        return
    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False) and entry.stat(follow_symlinks=False).st_mtime < cutoff:
                _remove_upload_session(entry.path)
        except OSError:
            logger.exception("Could not inspect temporary upload session %s", entry.path)


@app.post("/api/upload/chunk")
async def upload_file_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    chunk: UploadFile = File(...),
):
    if total_chunks < 1 or total_chunks > 10000 or chunk_index < 0 or chunk_index >= total_chunks:
        raise HTTPException(status_code=400, detail="Índice de fragmento inválido.")

    content = await chunk.read(UPLOAD_CHUNK_SIZE + 1)
    if len(content) > UPLOAD_CHUNK_SIZE:
        raise HTTPException(status_code=413, detail="El fragmento supera el tamaño permitido.")

    _cleanup_stale_upload_sessions()
    upload_dir = _upload_session_dir(upload_id)
    os.makedirs(upload_dir, exist_ok=True)
    chunk_path = os.path.join(upload_dir, f"{chunk_index:05d}.part")
    with open(chunk_path, "wb") as chunk_file:
        chunk_file.write(content)
    return {"success": True, "chunkIndex": chunk_index}


@app.post("/api/upload/complete")
async def complete_chunked_upload(
    upload_id: str = Form(...),
    filename: str = Form(...),
    total_chunks: int = Form(...),
    buses: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    if total_chunks < 1 or total_chunks > 10000:
        raise HTTPException(status_code=400, detail="Cantidad de fragmentos inválida.")

    upload_dir = _upload_session_dir(upload_id)
    safe_filename = os.path.basename(filename) or "archivo.csv"
    extension = os.path.splitext(safe_filename)[1]
    assembled_path = os.path.join(upload_dir, f"assembled{extension}")

    try:
        if not os.path.isdir(upload_dir):
            raise HTTPException(status_code=400, detail="No se encontraron fragmentos para esta carga.")
        with open(assembled_path, "wb") as assembled_file:
            for index in range(total_chunks):
                chunk_path = os.path.join(upload_dir, f"{index:05d}.part")
                if not os.path.isfile(chunk_path):
                    raise HTTPException(status_code=400, detail=f"Falta el fragmento {index + 1} del archivo.")
                with open(chunk_path, "rb") as chunk_file:
                    shutil.copyfileobj(chunk_file, assembled_file)

        return await run_in_threadpool(
            _import_telemetry_file,
            assembled_path,
            safe_filename,
            _parse_selected_buses(buses),
            db,
        )
    finally:
        _remove_upload_session(upload_dir)


@app.delete("/api/upload/chunk/{upload_id}")
def cancel_chunked_upload(upload_id: str):
    _remove_upload_session(_upload_session_dir(upload_id))
    return {"success": True}


@app.get("/api/telemetria")
def get_telemetria(
    idVehiculo: Optional[str] = None,
    idRuta: Optional[str] = None,
    fechaInicio: Optional[str] = None,
    fechaFin: Optional[str] = None,
    soloRetransmitida: Optional[bool] = None,
    rangoLatencia: Optional[str] = None,
    minLatenciaMin: Optional[float] = None,
    limit: Optional[int] = Query(None),
    offset: int = 0,
    db: Session = Depends(get_db)
):
    query = db.query(RegistroTelemetria)

    if idVehiculo:
        vehiculo_clean = idVehiculo.strip()
        query = query.filter(RegistroTelemetria.idVehiculo.ilike(f"%{vehiculo_clean}%"))

    if idRuta:
        query = query.filter(RegistroTelemetria.idRuta == idRuta.strip())

    if soloRetransmitida is not None:
        query = query.filter(RegistroTelemetria.tramaRetransmitida == soloRetransmitida)

    if rangoLatencia:
        query = query.filter(RegistroTelemetria.RangoLatencia.ilike(f"%{rangoLatencia.strip()}%"))

    if minLatenciaMin is not None:
        query = query.filter(RegistroTelemetria.latenciaMinutos >= minLatenciaMin)

    if fechaInicio:
        try:
            dt_inicio = datetime.datetime.fromisoformat(fechaInicio.replace("Z", ""))
            query = query.filter(RegistroTelemetria.fechaHoraLecturaDato >= dt_inicio)
        except Exception:
            pass

    if fechaFin:
        try:
            dt_fin = datetime.datetime.fromisoformat(fechaFin.replace("Z", ""))
            query = query.filter(RegistroTelemetria.fechaHoraLecturaDato <= dt_fin)
        except Exception:
            pass

    total_coincidentes = query.count()
    
    query_exec = query.order_by(
        desc(RegistroTelemetria.tramaRetransmitida),
        desc(RegistroTelemetria.latenciaMinutos),
        desc(RegistroTelemetria.fechaHoraLecturaDato)
    ).offset(offset)

    if limit and limit > 0:
        query_exec = query_exec.limit(limit)

    registros = query_exec.all()

    items = []
    for r in registros:
        items.append({
            "id": r.id,
            "idRuta": r.idRuta,
            "idVehiculo": r.idVehiculo,
            "fechaHoraLecturaDato": r.fechaHoraLecturaDato.isoformat() if r.fechaHoraLecturaDato else None,
            "fechaHoraEnvioDato": r.fechaHoraEnvioDato.isoformat() if r.fechaHoraEnvioDato else None,
            "latitud": r.latitud,
            "longitud": r.longitud,
            "tipoBus": r.tipoBus,
            "RangoLatencia": r.RangoLatencia,
            "tramaRetransmitida": r.tramaRetransmitida,
            "velocidadVehiculo": r.velocidadVehiculo,
            "aceleracionVehiculo": r.aceleracionVehiculo,
            "latenciaMinutos": r.latenciaMinutos,
            "archivoOrigen": r.archivoOrigen
        })

    return {
        "total": total_coincidentes,
        "limit": limit,
        "offset": offset,
        "items": items
    }

@app.get("/api/metricas")
def get_metricas(
    fechaInicio: Optional[str] = None,
    fechaFin: Optional[str] = None,
    db: Session = Depends(get_db)
):
    base_filter = []
    if fechaInicio:
        try:
            dt_inicio = datetime.datetime.fromisoformat(fechaInicio.replace("Z", ""))
            base_filter.append(RegistroTelemetria.fechaHoraLecturaDato >= dt_inicio)
        except Exception:
            pass
    if fechaFin:
        try:
            dt_fin = datetime.datetime.fromisoformat(fechaFin.replace("Z", ""))
            base_filter.append(RegistroTelemetria.fechaHoraLecturaDato <= dt_fin)
        except Exception:
            pass

    # Top buses with retransmissions
    top_vehiculos_query = db.query(
        RegistroTelemetria.idVehiculo,
        func.count(RegistroTelemetria.id).label("total_fallas"),
        func.avg(RegistroTelemetria.latenciaMinutos).label("latencia_promedio"),
        func.max(RegistroTelemetria.latenciaMinutos).label("latencia_max")
    ).filter(
        RegistroTelemetria.tramaRetransmitida == True,
        *base_filter
    ).group_by(RegistroTelemetria.idVehiculo).order_by(desc("total_fallas")).limit(10).all()

    top_vehiculos = [
        {
            "idVehiculo": row.idVehiculo,
            "totalFallas": row.total_fallas,
            "latenciaPromedioMin": round(row.latencia_promedio or 0.0, 1),
            "latenciaMaxMin": round(row.latencia_max or 0.0, 1)
        }
        for row in top_vehiculos_query
    ]

    # Latency range breakdown
    rangos_query = db.query(
        func.coalesce(RegistroTelemetria.RangoLatencia, "Normal / Sin Alerta").label("rango"),
        func.count(RegistroTelemetria.id).label("total")
    ).filter(*base_filter).group_by("rango").order_by(desc("total")).all()

    rangos_distribucion = [
        {"rango": row.rango, "total": row.total}
        for row in rangos_query
    ]

    # Top affected routes
    rutas_query = db.query(
        func.coalesce(RegistroTelemetria.idRuta, "Sin Ruta").label("ruta"),
        func.count(RegistroTelemetria.id).label("total_fallas")
    ).filter(
        RegistroTelemetria.tramaRetransmitida == True,
        *base_filter
    ).group_by("ruta").order_by(desc("total_fallas")).limit(8).all()

    rutas_afectadas = [
        {"ruta": row.ruta, "totalFallas": row.total_fallas}
        for row in rutas_query
    ]

    return {
        "topVehiculos": top_vehiculos,
        "rangosDistribucion": rangos_distribucion,
        "rutasAfectadas": rutas_afectadas
    }

@app.get("/api/vehiculos")
def get_vehiculos(db: Session = Depends(get_db)):
    rows = db.query(RegistroTelemetria.idVehiculo).distinct().order_by(RegistroTelemetria.idVehiculo).limit(200).all()
    return [r[0] for r in rows if r[0]]

@app.get("/api/rutas")
def get_rutas(db: Session = Depends(get_db)):
    rows = db.query(RegistroTelemetria.idRuta).distinct().order_by(RegistroTelemetria.idRuta).all()
    return [r[0] for r in rows if r[0]]

@app.delete("/api/limpiar-datos")
def limpiar_datos(db: Session = Depends(get_db)):
    db.query(RegistroTelemetria).delete()
    db.query(ArchivoCargado).delete()
    db.commit()
    return {"success": True, "message": "Base de datos reiniciada correctamente"}
