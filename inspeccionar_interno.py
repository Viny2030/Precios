"""
inspeccionar_interno.py — Abre los ZIPs anidados del dump SEPA
(sin descargar nada: usa data/manual/jueves.zip ya guardado)
y muestra los archivos internos + primeras líneas de cada uno,
para conocer los nombres reales de columnas antes de ajustar ingesta.py.
"""
import io
import zipfile

RUTA = "data/manual/jueves.zip"
CUANTOS_ZIPS_INTERNOS = 2   # con 2 alcanza para ver la estructura
LINEAS_A_MOSTRAR = 5

with zipfile.ZipFile(RUTA) as z_ext:
    internos = [n for n in z_ext.namelist() if n.lower().endswith(".zip")]
    # Elegimos internos medianos (ni vacíos ni gigantes) para inspección rápida
    internos_con_tamano = [(n, z_ext.getinfo(n).file_size) for n in internos]
    internos_con_tamano = [t for t in internos_con_tamano if 100_000 < t[1] < 10_000_000]
    internos_con_tamano.sort(key=lambda t: t[1])

    for nombre, tam in internos_con_tamano[:CUANTOS_ZIPS_INTERNOS]:
        print(f"\n{'='*70}\nZIP interno: {nombre} ({tam/1e6:.1f} MB)")
        with z_ext.open(nombre) as f:
            data = io.BytesIO(f.read())
        with zipfile.ZipFile(data) as z_int:
            for info in z_int.infolist():
                print(f"\n  📄 {info.filename}  ({info.file_size} bytes)")
                if info.file_size == 0 or info.filename.endswith("/"):
                    continue
                with z_int.open(info.filename) as archivo:
                    crudo = archivo.read(8000)
                texto = crudo.decode("utf-8", errors="replace")
                for i, linea in enumerate(texto.splitlines()[:LINEAS_A_MOSTRAR]):
                    print(f"     {i}: {linea[:200]}")