import requests, io, zipfile

headers = {'User-Agent': 'AnalizadorPreciosCABA/1.0 (+proyecto de monitoreo de precios bajo Ley 27.275)'}
r = requests.get('https://datos.gob.ar/api/3/action/package_show', params={'id':'produccion-precios-claros---base-sepa'}, headers=headers, timeout=20)
url_dia = next(rec['url'] for rec in r.json()['result']['resources'] if rec.get('name','').lower()=='jueves')
print('URL:', url_dia)

resp = requests.get(url_dia, headers=headers, timeout=600)
print('status:', resp.status_code, 'bytes:', len(resp.content))

with open('data/manual/jueves.zip', 'wb') as f:
    f.write(resp.content)
print('Guardado en data/manual/jueves.zip')

with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
    print('Archivos dentro del ZIP:')
    for n in z.namelist():
        print(' -', n, z.getinfo(n).file_size, 'bytes')