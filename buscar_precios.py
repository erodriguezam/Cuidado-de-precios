"""
Busca precios de productos en supermercados cercanos usando la API pública
que usa el propio sitio preciosclaros.gob.ar (Secretaría de Comercio).

Cómo funciona:
1. Pide las sucursales más cercanas a una latitud/longitud (San Justo, Bs. As. por defecto).
2. Para cada producto de la lista PRODUCTOS, busca precios en esas sucursales.
3. Guarda todo en data/precios.json, agrupado por cadena (bandera).

Uso:
    pip install requests
    python buscar_precios.py
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# --- Configuración -----------------------------------------------------

# San Justo, La Matanza, Buenos Aires (ajustar si hace falta más precisión)
HOME_LAT = -34.6796
HOME_LNG = -58.5636
CANTIDAD_SUCURSALES = 80  # cuántas sucursales pedirle a la API (después se filtran por distancia)
RADIO_KM = 8  # nos quedamos solo con las que estén a esta distancia o menos

# Productos a rastrear. Se puede agregar/sacar líneas libremente.
PRODUCTOS = [
    "leche entera",
    "pan lactal",
    "arroz",
    "aceite girasol",
    "fideos",
    "yerba mate",
    "papel higienico",
    "detergente",
    "azucar",
    "cafe molido",
]

BASE_URL = "https://d3e6htiiul5ek9.cloudfront.net/prod"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-AR,es;q=0.9",
    "Origin": "https://www.preciosclaros.gob.ar",
    "Referer": "https://www.preciosclaros.gob.ar/",
}

OUT_PATH = Path("data/precios.json")


# --- Funciones -----------------------------------------------------------

def obtener_sucursales(lat: float, lng: float, limit: int = 25) -> list[dict]:
    """Trae las sucursales más cercanas a un punto."""
    resp = requests.get(
        f"{BASE_URL}/sucursales",
        params={"lat": lat, "lng": lng, "limit": limit},
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    # La forma exacta de la respuesta puede variar; probamos las claves más comunes.
    return data.get("sucursales", data if isinstance(data, list) else [])


def id_sucursal(suc: dict) -> str:
    """Reconstruye el id compuesto que usa la API (comercio-bandera-sucursal),
    necesario para pedir precios."""
    for campo in ("id", "sucursal_id", "idSucursal"):
        if campo in suc:
            return str(suc[campo])
    # Fallback: algunos endpoints arman el id como "comercioId-banderaId-sucursalId"
    return "-".join(
        str(suc.get(c, "")) for c in ("comercioId", "banderaId", "sucursalId")
    )


def clave_match(suc: dict) -> str:
    """Clave banderaId-sucursalId, que es como el detalle de producto identifica
    cada sucursal (distinto del id compuesto de arriba)."""
    sucursal_id = suc.get("sucursalId")
    if sucursal_id is None:
        # el id compuesto tiene forma comercio-bandera-sucursal; nos quedamos con el último tramo
        sucursal_id = id_sucursal(suc).split("-")[-1]
    return f"{suc.get('banderaId')}-{sucursal_id}"


def nombre_cadena(suc: dict) -> str:
    for campo in ("banderaDescripcion", "comercioRazonSocial", "bandera", "nombre"):
        if suc.get(campo):
            return suc[campo]
    return "Desconocida"


def buscar_producto(term: str, sucursal_ids: list[str]) -> list[dict]:
    resp = requests.get(
        f"{BASE_URL}/productos",
        params={
            "string": term,
            "array_sucursales": ",".join(sucursal_ids),
            "offset": 0,
            "limit": 20,
            "sort": "-cant_sucursales_disponible",
        },
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return data
    for clave in ("productos", "resultados", "items", "data"):
        if clave in data:
            return data[clave]
    print(f"  (aviso: no reconozco la forma de la respuesta, claves: {list(data.keys())})")
    return []


def obtener_detalle_producto(id_producto: str, sucursal_ids: list[str]) -> dict:
    """Trae el detalle de un producto puntual, con precio por sucursal."""
    resp = requests.get(
        f"{BASE_URL}/producto",
        params={
            "id_producto": id_producto,
            "array_sucursales": ",".join(sucursal_ids),
        },
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def extraer_precios_por_cadena(detalle: dict, mapa_cadena: dict) -> tuple[dict, dict]:
    """Busca, dentro de la respuesta de detalle, la lista de precios por sucursal.
    Devuelve (precios_por_cadena, ofertas_por_cadena): el precio de lista más barato
    de cada cadena, y por separado cualquier promoción activa (promo1/promo2) que
    encuentre, con su descripción."""
    precios_por_cadena = {}
    ofertas_por_cadena = {}
    lista = detalle.get("sucursales") if isinstance(detalle, dict) else detalle
    if not lista:
        return precios_por_cadena, ofertas_por_cadena

    for entry in lista:
        if "message" in entry:
            continue  # esta sucursal no tiene el producto
        clave = f"{entry.get('banderaId')}-{entry.get('id')}"
        cadena = mapa_cadena.get(clave)
        if not cadena:
            continue

        info = entry.get("preciosProducto") or {}
        precio = info.get("precioLista")
        if precio:
            actual = precios_por_cadena.get(cadena)
            if actual is None or precio < actual:
                precios_por_cadena[cadena] = precio

        for promo_key in ("promo1", "promo2"):
            promo = info.get(promo_key) or {}
            precio_promo = promo.get("precio")
            if precio_promo:  # viene vacío ("") cuando no hay oferta activa
                actual = ofertas_por_cadena.get(cadena, {}).get("precio")
                if actual is None or precio_promo < actual:
                    ofertas_por_cadena[cadena] = {
                        "precio": precio_promo,
                        "descripcion": promo.get("descripcion") or "",
                    }

    return precios_por_cadena, ofertas_por_cadena


def main():
    print(f"Buscando sucursales cerca de ({HOME_LAT}, {HOME_LNG})...")
    sucursales = obtener_sucursales(HOME_LAT, HOME_LNG, CANTIDAD_SUCURSALES)
    print(f"  -> {len(sucursales)} sucursales encontradas en total")
    sucursales = [s for s in sucursales if (s.get("distanciaNumero") or 0) <= RADIO_KM]
    print(f"  -> {len(sucursales)} quedan dentro de {RADIO_KM} km")
    for s in sucursales:
        print(f"    - {nombre_cadena(s)} ({s.get('sucursalNombre')})")

    mapa_cadena = {clave_match(s): nombre_cadena(s) for s in sucursales}
    ids = [id_sucursal(s) for s in sucursales]

    resultado = []
    primer_detalle_mostrado = False
    for term in PRODUCTOS:
        print(f"Buscando '{term}'...")
        try:
            productos = buscar_producto(term, ids)
        except requests.RequestException as e:
            print(f"  ERROR buscando '{term}': {e}")
            continue

        print(f"  -> {len(productos)} productos encontrados")
        # por ahora nos quedamos con el primer resultado (el más disponible) por término
        for p in productos[:1]:
            id_producto = p.get("id")
            if not id_producto:
                continue
            try:
                detalle = obtener_detalle_producto(str(id_producto), ids)
            except requests.RequestException as e:
                print(f"  ERROR pidiendo detalle de '{p.get('nombre')}': {e}")
                continue

            precios_por_cadena, ofertas_por_cadena = extraer_precios_por_cadena(detalle, mapa_cadena)

            if not primer_detalle_mostrado:
                primer_detalle_mostrado = True
                print(f"  Precios encontrados para '{p.get('nombre')}': {precios_por_cadena}")
                if ofertas_por_cadena:
                    print(f"  ¡Ofertas encontradas!: {ofertas_por_cadena}")

            if precios_por_cadena:
                entrada = {
                    "termino_busqueda": term,
                    "nombre": p.get("nombre") or p.get("presentacion") or term,
                    "marca": p.get("marca"),
                    "precios": precios_por_cadena,
                }
                if ofertas_por_cadena:
                    entrada["ofertas"] = ofertas_por_cadena
                resultado.append(entrada)
            time.sleep(0.5)

        time.sleep(1)  # no golpear la API muy seguido

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(
            {
                "actualizado": datetime.now(timezone.utc).isoformat(),
                "origen": {"lat": HOME_LAT, "lng": HOME_LNG},
                "productos": resultado,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nListo. {len(resultado)} resultados guardados en {OUT_PATH}")


if __name__ == "__main__":
    main()
