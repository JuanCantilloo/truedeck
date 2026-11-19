import os
import io
import json
import datetime
import logging
import math
import tempfile
import uuid
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, Query, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, or_

if __package__:
    from .database import init_db, get_db
    from .models import RegistroTelemetria, ArchivoCargado, UploadChunk
    from .parser import parse_excel_or_csv_fast, iter_csv_telemetry_batches
else:
    from database import init_db, get_db
    from models import RegistroTelemetria, ArchivoCargado, UploadChunk
    from parser import parse_excel_or_csv_fast, iter_csv_telemetry_batches

app = FastAPI(title="TrueDeck Telemetría & Mapas API", version="1.0.0")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
FRONTEND_DIST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
# Vercel Functions reject request bodies above 4.5 MB, including multipart
# overhead. Three MiB chunks stay safely below that limit.
UPLOAD_CHUNK_SIZE = 3 * 1024 * 1024
logger = logging.getLogger(__name__)

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def read_root():
    frontend_index = os.path.join(FRONTEND_DIST_DIR, "index.html")
    index_file = frontend_index if os.path.exists(frontend_index) else os.path.join(STATIC_DIR, "index.html")
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
    total_registros = 0
    fallas_count = 0
    columns = [
        "idRuta", "idVehiculo", "fechaHoraLecturaDato", "fechaHoraEnvioDato",
        "latitud", "longitud", "tipoBus", "RangoLatencia", "tramaRetransmitida",
        "velocidadVehiculo", "aceleracionVehiculo", "latenciaMinutos",
        "archivoOrigen", "fechaCarga",
    ]
    date_columns = {"fechaHoraLecturaDato", "fechaHoraEnvioDato", "fechaCarga"}
    try:
        if filename.lower().endswith('.csv') and isinstance(content, str):
            batches = iter_csv_telemetry_batches(content, filename, selected_buses)
        else:
            parsed = parse_excel_or_csv_fast(content, filename, selected_buses)
            batches = [parsed]

        for tuples_data, batch_rows, batch_failures in batches:
            if tuples_data:
                records = []
                for values in tuples_data:
                    record = dict(zip(columns, values))
                    for column, value in record.items():
                        if hasattr(value, "item"):
                            value = value.item()
                        if isinstance(value, float) and math.isnan(value):
                            value = None
                        record[column] = value
                    for column in date_columns:
                        value = record[column]
                        if isinstance(value, str) and value:
                            record[column] = datetime.datetime.fromisoformat(value)
                    records.append(record)
                db.execute(RegistroTelemetria.__table__.insert(), records)
            total_registros += batch_rows
            fallas_count += batch_failures

        if total_registros == 0:
            db.rollback()
            raise HTTPException(status_code=400, detail="El archivo no contiene registros válidos para la selección indicada.")

        db.add(
            ArchivoCargado(
                nombre=filename,
                totalRegistros=total_registros,
                totalConFalla=fallas_count,
                fechaCarga=datetime.datetime.utcnow(),
            )
        )
        db.commit()
    except (ValueError, OSError) as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error al procesar archivo: {str(e)}")
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar registros en base de datos: {str(e)}")

    return {
        "success": True,
        "filename": filename,
        "registrosImportados": total_registros,
        "totalConFalla": fallas_count,
        "busesSeleccionados": selected_buses,
    }


def _normalize_upload_id(upload_id: str) -> str:
    try:
        return str(uuid.UUID(upload_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Identificador de carga inválido.")


def _cleanup_stale_upload_sessions(db: Session) -> None:
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    db.query(UploadChunk).filter(UploadChunk.updated_at < cutoff).delete(synchronize_session=False)
    db.commit()


@app.post("/api/upload/chunk")
async def upload_file_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    chunk: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if total_chunks < 1 or total_chunks > 10000 or chunk_index < 0 or chunk_index >= total_chunks:
        raise HTTPException(status_code=400, detail="Índice de fragmento inválido.")

    content = await chunk.read(UPLOAD_CHUNK_SIZE + 1)
    if len(content) > UPLOAD_CHUNK_SIZE:
        raise HTTPException(status_code=413, detail="El fragmento supera el tamaño permitido.")

    safe_id = _normalize_upload_id(upload_id)
    _cleanup_stale_upload_sessions(db)
    db.query(UploadChunk).filter(
        UploadChunk.upload_id == safe_id,
        UploadChunk.chunk_index == chunk_index,
    ).delete(synchronize_session=False)
    db.add(UploadChunk(
        upload_id=safe_id,
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        content=content,
        updated_at=datetime.datetime.utcnow(),
    ))
    db.commit()
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

    safe_id = _normalize_upload_id(upload_id)
    safe_filename = os.path.basename(filename) or "archivo.csv"
    extension = os.path.splitext(safe_filename)[1]
    assembled_path = os.path.join(
        tempfile.gettempdir(), f"truedeck-{safe_id}-{uuid.uuid4().hex}{extension}"
    )

    try:
        chunk_query = db.query(UploadChunk).filter(UploadChunk.upload_id == safe_id)
        if chunk_query.count() != total_chunks:
            raise HTTPException(status_code=400, detail="No se encontraron fragmentos para esta carga.")
        with open(assembled_path, "wb") as assembled_file:
            expected_index = 0
            for saved_chunk in chunk_query.order_by(UploadChunk.chunk_index).yield_per(1):
                if saved_chunk.chunk_index != expected_index or saved_chunk.total_chunks != total_chunks:
                    raise HTTPException(status_code=400, detail=f"Falta el fragmento {expected_index + 1} del archivo.")
                assembled_file.write(saved_chunk.content)
                expected_index += 1

        return await run_in_threadpool(
            _import_telemetry_file,
            assembled_path,
            safe_filename,
            _parse_selected_buses(buses),
            db,
        )
    finally:
        try:
            if os.path.exists(assembled_path):
                os.remove(assembled_path)
            db.query(UploadChunk).filter(UploadChunk.upload_id == safe_id).delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not remove uploaded chunks for session %s", safe_id)


@app.delete("/api/upload/chunk/{upload_id}")
def cancel_chunked_upload(upload_id: str, db: Session = Depends(get_db)):
    safe_id = _normalize_upload_id(upload_id)
    db.query(UploadChunk).filter(UploadChunk.upload_id == safe_id).delete(synchronize_session=False)
    db.commit()
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


# Vercel serves the built Vite frontend from the same FastAPI deployment.
# Keep this mount last so the API routes above take precedence.
if os.path.isdir(FRONTEND_DIST_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST_DIR, html=True), name="frontend")
