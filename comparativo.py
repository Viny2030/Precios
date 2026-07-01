import pandas as pd

# URL de la API de Series de Tiempo del Ministerio de Economía / INDEC
URL_API_INDEC_IPC = "https://apis.datos.gob.ar/series/api/series/?ids=148.3_INDEC_GBA_01_0_24&format=csv"

def obtener_historico_indec():
    print("Conectando con la API de Series de Tiempo (INDEC)...")
    try:
        # Descarga el CSV de la serie de Alimentos para GBA/CABA directamente
        df_indec = pd.read_csv(URL_API_INDEC_IPC)
        
        # Renombrar columnas para tu base de datos
        df_indec.columns = ['fecha', 'indice_oficial_alimentos']
        
        # Convertir la fecha a formato estándar (YYYY-MM)
        df_indec['fecha'] = pd.to_datetime(df_indec['fecha']).dt.to_period('M')
        
        print(f"Serie oficial recuperada. Último dato disponible: {df_indec['fecha'].max()}")
        return df_indec
    except Exception as e:
        print(f"Error al conectar con la API de series: {e}")
        return pd.DataFrame()
