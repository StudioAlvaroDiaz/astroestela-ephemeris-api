# astroestela-ephemeris-api

Motor de cálculo astronómico de [astroestela.com](https://astroestela.com): posiciones planetarias,
Nodos, Lilith, Quirón, Ascendente, Medio Cielo, 12 casas y aspectos, a partir de efemérides
locales de Swiss Ephemeris (derivadas de las efemérides JPL de la NASA). No llama a ningún
servicio externo: cada cálculo tarda milisegundos.

Lo consume el plugin de WordPress de astroestela.com, servidor a servidor, con peticiones
firmadas. El navegador del visitante nunca habla con esta API.

## Licencia

Este proyecto se publica bajo **GNU AGPL v3 o posterior** (ver `LICENSE`), porque usa
Swiss Ephemeris, © 1997-2021 Astrodienst AG, Suiza, distribuida bajo AGPL. El código fuente
de la versión en servicio se anuncia en `GET /source` y en la cabecera `X-Source-Code`.

## Endpoints

| Método | Ruta | Acceso | Uso |
| --- | --- | --- | --- |
| GET | `/health` | Público | Monitorización |
| GET | `/source` | Público | Enlace al código fuente (AGPL) |
| GET | `/v1/positions?datetime_utc=2026-11-11T19:00:00Z` | Firmado + IP permitida | Posiciones del momento (tránsitos) |
| POST | `/v1/chart` | Firmado + IP permitida | Carta natal completa |

Cuerpo de `/v1/chart`:

```json
{
  "datetime_local": "1990-05-15T14:30:00",
  "lat": 40.4168,
  "lon": -3.7038,
  "house_system": "P"
}
```

- Se envía `datetime_local` (la zona horaria histórica se detecta por coordenadas) **o** `datetime_utc`.
- `house_system`: `P` Placidus, `K` Koch, `O` Porfirio, `R` Regiomontanus, `C` Campanus, `E` iguales, `W` signos enteros.
- `timezone_name` (opcional): zona IANA si se quiere forzar.
- `fold` (opcional, 0 o 1): para horas que ocurrieron dos veces por el cambio de horario.

La respuesta incluye `metadata`, `angles`, `houses`, `positions` (con casa, velocidad y
retrogradación), `aspects` (con orbe y fase `applying`/`separating`) y `warnings`.

Errores: `{"error": {"code": "...", "message": "..."}}`. Códigos de entrada que el frontend
debe tratar: `nonexistent_local_time` (pedir otra hora), `date_out_of_range`,
`timezone_not_found`, `invalid_datetime`, `invalid_request`.

Avisos (`warnings`): `ambiguous_local_time`, `house_system_fallback` (Placidus no existe por
encima de ~66° de latitud; se usa Porfirio).

## Autenticación (HMAC)

Cada petición a `/v1/*` lleva dos cabeceras:

- `X-Astro-Timestamp`: hora Unix en segundos (vale 5 minutos).
- `X-Astro-Signature`: HMAC-SHA256 en hexadecimal, con el secreto compartido, de:

```
<timestamp>\n<MÉTODO>\n<ruta con query>\n<sha256 hex del cuerpo>
```

Ejemplo en PHP (WordPress):

```php
$body = wp_json_encode($payload);
$ts   = (string) time();
$path = '/v1/chart';
$sig  = hash_hmac('sha256', "$ts\nPOST\n$path\n" . hash('sha256', $body), ASTRO_API_SECRET);

wp_remote_post(ASTRO_API_URL . $path, [
    'headers' => [
        'Content-Type'      => 'application/json',
        'X-Astro-Timestamp' => $ts,
        'X-Astro-Signature' => $sig,
    ],
    'body'    => $body,
    'timeout' => 10,
]);
```

El secreto nunca viaja por la red. Para rotarlo sin cortar el servicio: añadir el nuevo al
principio de `EPHEM_HMAC_SECRETS` (separado por coma), actualizar WordPress y quitar el viejo.

## Despliegue en el VPS (Docker + Traefik existente)

Requisitos: el Traefik de `/docker/n8n` (red `n8n_default`, resolver `mytlschallenge`) y el
registro DNS `api-staging.astroestela.com` apuntando al VPS.

```bash
# 1. Comprobar la versión de Traefik (v3 → "ipallowlist"; v2 → cambiar a "ipwhitelist")
docker exec n8n-traefik-1 traefik version

# 2. Código
mkdir -p /docker && cd /docker
git clone https://github.com/StudioAlvaroDiaz/astroestela-ephemeris-api.git
cd astroestela-ephemeris-api

# 3. Efemérides (verificadas por SHA-256)
./scripts/fetch_ephemeris.sh ./data

# 4. Configuración
cp .env.example .env
sed -i "s/^EPHEM_HMAC_SECRETS=.*/EPHEM_HMAC_SECRETS=$(openssl rand -hex 32)/" .env
chmod 600 .env
grep EPHEM_HMAC_SECRETS .env   # copiar este valor a wp-config.php de WordPress

# 5. Arrancar
docker compose up -d --build
docker compose ps        # debe quedar "healthy"
docker compose logs -f   # Ctrl+C para salir
```

Comprobaciones:

```bash
curl https://api-staging.astroestela.com/health            # 200 desde cualquier sitio
curl -i https://api-staging.astroestela.com/v1/chart        # 403 fuera de la IP permitida
```

Actualizar a una versión nueva: `git pull && docker compose up -d --build`.

## Desarrollo y pruebas

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
./scripts/fetch_ephemeris.sh ./data
EPHEM_DATA_DIR=./data pytest -q
```

Sin la carpeta `data/` las pruebas usan el modelo Moshier (menos preciso, sin Quirón).
Las cartas de referencia de `tests/test_engine.py` están anonimizadas: solo lugar, fecha y hora.

Las dependencias directas están en `requirements.in`; `requirements.txt` fija todas las
versiones para que una reconstrucción no cambie nada sin querer.
