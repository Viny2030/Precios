def persistir_registros(df: pd.DataFrame) -> tuple[int, int]:
    """
    Vuelca el DataFrame procesado a la base: primero actualiza/crea las
    filas de maestro_productos, después inserta los registros de precio.
    Devuelve (productos_nuevos, precios_insertados).

    AGREGADO 2026-09-01: reescrito para insertar en bloques (bulk_insert_mappings)
    en vez de un db.add() por fila -- con cientos de miles de filas, el enfoque
    anterior (un objeto ORM por fila, todo pendiente hasta un solo commit final)
    era tan lento y pesado que el proceso se quedaba colgado sin terminar nunca
    la Persistencia.
    """
    if df.empty:
        return 0, 0
    db = SessionLocal()
    productos_nuevos = 0
    precios_insertados = 0
    LOTE = 20_000
    try:
        eans_conocidos = {p.ean for p in db.query(MaestroProducto.ean).all()}

        # 1) Productos nuevos: armar la lista completa y un solo insert en bloque.
        nuevos_productos = []
        vistos = set()
        for ean, grupo in df.groupby("ean"):
            ean_int = int(ean)
            if ean_int in eans_conocidos or ean_int in vistos:
                continue
            fila = grupo.iloc[0]
            nuevos_productos.append({
                "ean": ean_int,
                "descripcion": fila.get("nombre"),
                "marca": fila.get("marca"),
                "coicop_subclase": fila.get("coicop_subclase") if pd.notna(fila.get("coicop_subclase")) else None,
                "unidad_medida": fila.get("unidad_medida") if pd.notna(fila.get("unidad_medida")) else None,
                "contenido_neto": float(fila["contenido_neto"]) if pd.notna(fila.get("contenido_neto")) else None,
            })
            vistos.add(ean_int)
        if nuevos_productos:
            db.bulk_insert_mappings(MaestroProducto, nuevos_productos)
            productos_nuevos = len(nuevos_productos)
        db.commit()

        # 2) Precios: insertar en lotes de 20.000, con commit después de cada
        # lote -- así nunca se acumula todo en una sola transacción gigante.
        validos = df.dropna(subset=["precio", "fecha"])
        buffer = []
        for fila in validos.itertuples(index=False):
            buffer.append({
                "ean": int(fila.ean),
                "precio_lista": float(fila.precio),
                "fecha": pd.to_datetime(fila.fecha).date(),
                "sucursal_caba_id": str(fila.sucursal) if pd.notna(fila.sucursal) else None,
                "cadena": str(fila.cadena) if pd.notna(fila.cadena) else None,
            })
            if len(buffer) >= LOTE:
                db.bulk_insert_mappings(RegistroPrecio, buffer)
                db.commit()
                precios_insertados += len(buffer)
                buffer.clear()
        if buffer:
            db.bulk_insert_mappings(RegistroPrecio, buffer)
            db.commit()
            precios_insertados += len(buffer)
    except Exception as e:
        db.rollback()
        logger.error(f"Error al persistir: {e}")
        raise
    finally:
        db.close()
    return productos_nuevos, precios_insertados