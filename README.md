# Analizador de Precios CABA - Nueva Canasta COICOP

Este sistema automatizado realiza el *Nowcasting* y cálculo mensual del Índice de Precios de Alimentos y Bebidas para la Ciudad Autónoma de Buenos Aires (CABA). 

El motor está diseñado bajo estrictas pautas metodológicas utilizando la **Nueva Canasta de Consumo (ENGHo 2017-2018)** y la clasificación internacional **COICOP**, adelantándose al empalme oficial del INDEC.

## ⚖️ Marco Legal y Transparencia
De acuerdo con la **Ley N° 27.275 de Derecho de Acceso a la Información Pública**, este desarrollo se nutre exclusivamente de fuentes de información oficiales, transparentes y en formatos abiertos provistas por el Ministerio de Economía de la Nación y el Portal BA Data. No utiliza datos sintéticos ni simulados.

## 🚀 Arquitectura del Pipeline
1. **Ingesta:** Descarga diaria automatizada de los Dumps masivos (`.zip`) del SEPA (Precios Claros).
2. **Filtrado:** Procesamiento por bloques (`chunks`) en Pandas para aislar únicamente las sucursales de CABA, protegiendo el consumo de memoria RAM.
3. **Clasificación:** Mapeo taxonómico mediante códigos universales de barra (EAN/GTIN) hacia las subclases COICOP.
4. **Cálculo:** Agregación estadística utilizando la **Fórmula de Jevons** (media geométrica) para índices elementales y ponderaciones fijas de Laspeyres.

## 🛠️ Instalación y Uso

1. Clonar el repositorio y abrirlo en PyCharm.
2. Instalar las dependencias del entorno virtual:
   ```bash
   pip install -r requirements.txt
