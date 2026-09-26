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
CANTIDAD_SUCURSALES = 25  # cuántas sucursales cercanas traer

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
    """Reconstruye el id compuesto que usa la API (comercio-bandera-sucursal)."""
    for campo in ("id", "sucursal_id", "idSucursal"):
        if campo in suc:
            return str(suc[campo])
    # Fallback: algunos endpoints arman el id como "comercioId-banderaId-sucursalId"
    return "-".join(
        str(suc.get(c, "")) for c in ("comercioId", "banderaId", "sucursalId")
    )


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
    return data.get("productos", [])


def main():
    print(f"Buscando sucursales cerca de ({HOME_LAT}, {HOME_LNG})...")
    sucursales = obtener_sucursales(HOME_LAT, HOME_LNG, CANTIDAD_SUCURSALES)
    print(f"  -> {len(sucursales)} sucursales encontradas")
    if sucursales:
        print("  Ejemplo de respuesta cruda (para ajustar nombres de campo si hace falta):")
        print(" ", json.dumps(sucursales[0], ensure_ascii=False)[:400])

    mapa_cadena = {id_sucursal(s): nombre_cadena(s) for s in sucursales}
    ids = list(mapa_cadena.keys())

    resultado = []
    for term in PRODUCTOS:
        print(f"Buscando '{term}'...")
        try:
            productos = buscar_producto(term, ids)
        except requests.RequestException as e:
            print(f"  ERROR buscando '{term}': {e}")
            continue

        for p in productos:
            precios_por_cadena = {}
            # La API suele traer un array de precios por sucursal dentro del producto;
            # probamos los nombres de campo más habituales.
            for campo_lista in ("precios", "sucursales", "preciosPorSucursal"):
                if campo_lista in p:
                    for entry in p[campo_lista]:
                        suc_id = str(
                            entry.get("id_sucursal") or entry.get("sucursalId") or ""
                        )
                        precio = entry.get("precio") or entry.get("precioLista")
                        cadena = mapa_cadena.get(suc_id)
                        if cadena and precio:
                            # nos quedamos con el más barato de esa cadena
                            actual = precios_por_cadena.get(cadena)
                            if actual is None or precio < actual:
                                precios_por_cadena[cadena] = precio
                    break

            if precios_por_cadena:
                resultado.append({
                    "termino_busqueda": term,
                    "nombre": p.get("nombre") or p.get("presentacion") or term,
                    "marca": p.get("marca"),
                    "precios": precios_por_cadena,
                })

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
