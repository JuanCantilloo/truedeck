from sqlalchemy import BigInteger, Column, Integer, String, Float, Boolean, DateTime, Index, LargeBinary
from sqlalchemy.orm import declarative_base
import datetime

Base = declarative_base()

class RegistroTelemetria(Base):
    __tablename__ = "telemetria"

    id = Column(BigInteger, primary_key=True, index=True)
    idRuta = Column(String(50), nullable=True)
    idVehiculo = Column(String(50), index=True, nullable=False)
    fechaHoraLecturaDato = Column(DateTime, index=True, nullable=True)
    fechaHoraEnvioDato = Column(DateTime, index=True, nullable=True)
    latitud = Column(Float, nullable=True)
    longitud = Column(Float, nullable=True)
    tipoBus = Column(String(20), nullable=True)
    RangoLatencia = Column(String(50), nullable=True)
    tramaRetransmitida = Column(Boolean, index=True, default=False)
    velocidadVehiculo = Column(Float, default=0.0)
    aceleracionVehiculo = Column(Float, default=0.0)
    latenciaMinutos = Column(Float, default=0.0, index=True)
    archivoOrigen = Column(String(255), nullable=True)
    fechaCarga = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        Index("idx_vehiculo_fecha", "idVehiculo", "fechaHoraLecturaDato"),
        Index("idx_retrans_fecha", "tramaRetransmitida", "fechaHoraLecturaDato"),
    )

class ArchivoCargado(Base):
    __tablename__ = "archivos_cargados"

    id = Column(BigInteger, primary_key=True, index=True)
    nombre = Column(String(255), nullable=False)
    totalRegistros = Column(Integer, default=0)
    totalConFalla = Column(Integer, default=0)
    fechaCarga = Column(DateTime, default=datetime.datetime.utcnow)


class UploadChunk(Base):
    __tablename__ = "upload_chunks"

    upload_id = Column(String(36), primary_key=True)
    chunk_index = Column(Integer, primary_key=True)
    total_chunks = Column(Integer, nullable=False)
    content = Column(LargeBinary, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_upload_chunks_updated_at", "updated_at"),
    )
