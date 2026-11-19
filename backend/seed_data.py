import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "backend"))

from database import init_db, SessionLocal
from models import RegistroTelemetria, ArchivoCargado
from parser import parse_excel_or_csv

init_db()
db = SessionLocal()

sample_file = os.path.join(BASE_DIR, "sample_test.xlsx")
if os.path.exists(sample_file):
    records = parse_excel_or_csv(sample_file, "ejemplo_captura.xlsx")
    objs = [RegistroTelemetria(**r) for r in records]
    db.bulk_save_objects(objs)

    fallas = sum(1 for r in records if r["tramaRetransmitida"])
    archivo = ArchivoCargado(
        nombre="ejemplo_captura.xlsx",
        totalRegistros=len(records),
        totalConFalla=fallas
    )
    db.add(archivo)
    db.commit()
    print(f"Cargados exitosamente {len(records)} registros de prueba iniciales.")
else:
    print("Archivo de prueba no encontrado.")
db.close()
