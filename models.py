"""
models.py — Esquema de base de datos (SQLAlchemy 2.x)

Implementa las 3 tablas del diseño original más una de caché para la serie
comparativa del INDEC/GCBA.
"""
from __future__ import annotations

from sqlalchemy import (
    create_engine, Column, Integer, BigInteger, String, Numeric, Date,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

import config

Base = declarative_base()


class MaestroProducto(Base):
    """Diccionario EAN -> descripción, marca y subclase COICOP."""
    __tablename__ = "maestro_productos"

    ean = Column(BigInteger, primary_key=True)
    descripcion = Column(String(300))
    marca = Column(String(150))
    coicop_subclase = Column(String(20), ForeignKey("ponderaciones_coicop.coicop_subclase"), nullable=True)
    unidad_medida = Column(String(20), nullable=True)   # kg | l | unidad
    contenido_neto = Column(Numeric(12, 4), nullable=True)  # para normalizar precio/unidad

    registros = relationship("RegistroPrecio", back_populates="producto")
    ponderacion = relationship("PonderacionCoicop", back_populates="productos")


class RegistroPrecio(Base):
    """Un precio observado de un EAN en una sucursal de CABA en una fecha."""
    __tablename__ = "registro_precios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ean = Column(BigInteger, ForeignKey("maestro_productos.ean"), nullable=False, index=True)
    precio_lista = Column(Numeric(12, 2), nullable=False)
    fecha = Column(Date, nullable=False, index=True)
    sucursal_caba_id = Column(String(50), nullable=True)
    cadena = Column(String(100), nullable=True)

    producto = relationship("MaestroProducto", back_populates="registros")

    __table_args__ = (
        Index("ix_registro_ean_fecha", "ean", "fecha"),
    )


class PonderacionCoicop(Base):
    """Vector de ponderaciones de la nueva canasta (ENGHo 2017-2018) para CABA."""
    __tablename__ = "ponderaciones_coicop"

    coicop_subclase = Column(String(20), primary_key=True)
    descripcion_rubro = Column(String(300))
    ponderacion_caba = Column(Numeric(10, 6))  # peso relativo, suma ~1.0 dentro de su división
    division = Column(String(2))               # "01" o "02"
    fuente = Column(String(100), default="ENGHo 2017-2018")

    productos = relationship("MaestroProducto", back_populates="ponderacion")


class SerieComparativaINDEC(Base):
    """Caché local de la serie oficial (INDEC/GCBA) para comparar contra el índice propio."""
    __tablename__ = "serie_comparativa_indec"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(Date, nullable=False)
    serie_id = Column(String(60), nullable=False)   # id de la serie en datos.gob.ar
    valor = Column(Numeric(14, 4), nullable=False)

    __table_args__ = (
        UniqueConstraint("fecha", "serie_id", name="uq_fecha_serie"),
    )


class IndiceCalculado(Base):
    """Resultado mensual/semanal del índice propio, por nivel de agregación."""
    __tablename__ = "indice_calculado"

    id = Column(Integer, primary_key=True, autoincrement=True)
    periodo = Column(String(10), nullable=False)      # "2026-01" (mensual) o "2026-W05" (semanal)
    nivel = Column(String(20), nullable=False)         # "general" | "coicop_subclase"
    coicop_subclase = Column(String(20), nullable=True)  # null si nivel == "general"
    indice_valor = Column(Numeric(14, 6), nullable=False)   # base PERIODO_BASE = 100
    variacion_pct = Column(Numeric(8, 4), nullable=True)    # vs. mes/semana anterior
    cantidad_variedades = Column(Integer, nullable=True)    # cuántos EAN entraron al cálculo

    __table_args__ = (
        UniqueConstraint("periodo", "nivel", "coicop_subclase", name="uq_periodo_nivel_subclase"),
    )


engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def crear_tablas():
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    crear_tablas()
    print(f"Tablas creadas en: {config.DATABASE_URL}")