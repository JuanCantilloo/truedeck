import re
import io
import datetime
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple, Optional

# Single-pass Spanish month replacement using one compiled regex with a function
_MONTH_MAP = {
    'ene': '01', 'enero': '01',
    'feb': '02', 'febrero': '02',
    'mar': '03', 'marzo': '03',
    'abr': '04', 'abril': '04',
    'may': '05', 'mayo': '05',
    'jun': '06', 'junio': '06',
    'jul': '07', 'julio': '07',
    'ago': '08', 'agosto': '08',
    'sep': '09', 'septiembre': '09', 'set': '09',
    'oct': '10', 'octubre': '10',
    'nov': '11', 'noviembre': '11',
    'dic': '12', 'diciembre': '12',
}

# Build ONE combined pattern matching all month names, longest first to avoid prefix issues
_ALL_MONTHS = sorted(_MONTH_MAP.keys(), key=len, reverse=True)
_MONTH_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(m) for m in _ALL_MONTHS) + r')\b',
    flags=re.IGNORECASE
)

def _replace_month(m):
    return _MONTH_MAP[m.group(1).lower()]

def clean_spanish_dates_series(series: pd.Series) -> pd.Series:
    """
    Fast single-pass vectorized conversion of Spanish date strings like
    '26 oct 2026, 4:10:13' into pd.Timestamp objects.
    Uses ONE combined regex instead of 12 separate passes.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return series

    s = series.astype(str).str.strip()

    # 1. Single-pass apply for Spanish month names (much faster than 12 str.replace calls)
    has_alpha = s.str.contains(r'[a-zA-Z]', regex=True, na=False)

    if has_alpha.any():
        def fast_replace(val):
            if not isinstance(val, str):
                return val
            # Replace month name
            val = _MONTH_PATTERN.sub(_replace_month, val)
            # Remove 'de' and commas
            val = re.sub(r'\bde\b', '', val, flags=re.IGNORECASE)
            val = val.replace(',', '')
            return val

        s_alpha = s[has_alpha]
        s_replaced = s_alpha.apply(fast_replace)
        s = s.copy()
        s[has_alpha] = s_replaced

    # 2. Vectorized parse (C engine)
    return pd.to_datetime(s, dayfirst=True, errors='coerce')


def parse_excel_or_csv_fast(file_bytes_or_path: Any, filename: str, selected_buses: Optional[List[str]] = None) -> Tuple[List[tuple], int, int]:
    """
    Ultra-fast vectorized parser using calamine (Rust) for Excel or C-engine for CSV.
    Returns (rows_for_database_insert, total_records, fallas_count).
    Optional selected_buses can be used to restrict import to a subset of bus IDs.
    """
    if hasattr(file_bytes_or_path, 'read'):
        content = file_bytes_or_path
    else:
        content = file_bytes_or_path

    fn_lower = filename.lower()
    if fn_lower.endswith('.csv'):
        df = pd.read_csv(content, engine='c', low_memory=False)
    else:
        try:
            df = pd.read_excel(content, engine='calamine')
        except Exception:
            try:
                df = pd.read_excel(content, engine='openpyxl')
            except Exception as e2:
                raise ValueError(f"No se pudo leer el archivo Excel: {e2}")

    # Normalize column names for flexible matching
    cols_map = {}
    for col in df.columns:
        norm = re.sub(r'[^a-zA-Z0-9]', '', str(col).lower())
        cols_map[norm] = col

    def get_col(possible_names):
        for name in possible_names:
            norm_name = re.sub(r'[^a-zA-Z0-9]', '', name.lower())
            if norm_name in cols_map:
                return cols_map[norm_name]
        return None

    c_ruta    = get_col(['idRuta', 'ruta', 'id_ruta'])
    c_vehiculo = get_col(['idVehiculo', 'vehiculo', 'id_vehiculo', 'codigo_bus', 'bus'])
    c_lectura  = get_col(['fechaHoraLecturaDato', 'fechaLectura', 'fechahora_lectura', 'lectura'])
    c_envio    = get_col(['fechaHoraEnvioDato', 'fechaEnvio', 'fechahora_envio', 'envio'])
    c_coords   = get_col(['Coordenadas', 'coordenadas', 'lat_long', 'posicion'])
    c_tipo     = get_col(['tipoBus', 'tipobus', 'tipo_bus'])
    c_rango    = get_col(['RangoLatencia', 'rangolatencia', 'rango_latencia', 'rango'])
    c_retrans  = get_col(['tramaRetransmitida', 'tramaretransmitida', 'retransmitida', 'retransmision', 'descuadre'])
    c_vel      = get_col(['velocidadVehiculo', 'velocidad', 'vel'])
    c_acel     = get_col(['aceleracionVehiculo', 'aceleracion', 'acel'])

    if not c_vehiculo:
        c_vehiculo = df.columns[1] if len(df.columns) > 1 else df.columns[0]

    # Drop rows with no vehicle ID
    df = df[df[c_vehiculo].notna()].copy()
    df[c_vehiculo] = df[c_vehiculo].astype(str).str.strip()
    df = df[~df[c_vehiculo].isin(['nan', 'None', '', 'null'])]

    if selected_buses:
        allowed = {str(v).strip().upper() for v in selected_buses if str(v).strip()}
        if allowed:
            df[c_vehiculo] = df[c_vehiculo].astype(str).str.strip().str.upper()
            df = df[df[c_vehiculo].isin(allowed)].copy()
        else:
            return [], 0, 0

    total_rows = len(df)
    if total_rows == 0:
        return [], 0, 0

    # 1. Fast vectorized Dates
    df['dt_lectura'] = clean_spanish_dates_series(df[c_lectura]) if c_lectura else pd.NaT
    df['dt_envio']   = clean_spanish_dates_series(df[c_envio])   if c_envio  else pd.NaT

    # 2. Latency in minutes
    diff_sec = (df['dt_envio'] - df['dt_lectura']).dt.total_seconds()
    df['latencia_min'] = diff_sec.clip(lower=0).fillna(0.0).div(60.0).round(2)

    # 3. Coordinates - single vectorized split
    if c_coords:
        coords_str = df[c_coords].astype(str).str.strip()
        coords_split = coords_str.str.split(',', n=1, expand=True)
        df['lat'] = pd.to_numeric(coords_split[0], errors='coerce')
        df['lng'] = pd.to_numeric(coords_split[1] if coords_split.shape[1] > 1 else pd.Series(dtype=str), errors='coerce')
    else:
        df['lat'] = np.nan
        df['lng'] = np.nan

    # 4. Vectorized Boolean
    if c_retrans:
        col = df[c_retrans]
        if col.dtype == bool:
            df['retrans_bool'] = col
        elif pd.api.types.is_integer_dtype(col):
            df['retrans_bool'] = col == 1
        else:
            s = col.astype(str).str.strip().str.lower()
            df['retrans_bool'] = s.isin(['true', '1', 't', 'si', 'sí', 'verdadero', 'yes'])
    else:
        df['retrans_bool'] = False

    fallas_count = int(df['retrans_bool'].sum())

    # 5. String fields - vectorized cleanup
    def clean_str_col(col_name):
        if col_name and col_name in df.columns:
            s = df[col_name].astype(str).str.strip()
            return s.where(~s.isin(['nan', 'None', 'null', 'NaN', '']), other=None)
        return pd.Series([None] * total_rows, index=df.index)

    df['ruta_str'] = clean_str_col(c_ruta)
    df['tipo_str'] = clean_str_col(c_tipo)
    df['rango_str'] = clean_str_col(c_rango)
    df['vel_val']  = pd.to_numeric(df[c_vel],  errors='coerce').fillna(0.0) if c_vel  else 0.0
    df['acel_val'] = pd.to_numeric(df[c_acel], errors='coerce').fillna(0.0) if c_acel else 0.0

    # 6. Format dates as ISO strings; the SQLAlchemy layer converts these to
    # native datetimes for both SQLite and PostgreSQL.
    df['lectura_iso'] = df['dt_lectura'].dt.strftime('%Y-%m-%d %H:%M:%S').where(df['dt_lectura'].notna(), None)
    df['envio_iso']   = df['dt_envio'].dt.strftime('%Y-%m-%d %H:%M:%S').where(df['dt_envio'].notna(),   None)
    now_iso = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    # 7. Build output DataFrame and convert to list of tuples (fastest approach)
    out_df = pd.DataFrame({
        'ruta':     df['ruta_str'].values,
        'vehiculo': df[c_vehiculo].values,
        'lectura':  df['lectura_iso'].values,
        'envio':    df['envio_iso'].values,
        'lat':      df['lat'].values,
        'lng':      df['lng'].values,
        'tipo':     df['tipo_str'].values,
        'rango':    df['rango_str'].values,
        'retrans':  df['retrans_bool'].values,
        'vel':      df['vel_val'].values,
        'acel':     df['acel_val'].values,
        'latencia': df['latencia_min'].values,
        'archivo':  filename,
        'carga':    now_iso
    })

    # Replace numpy nan/NaT with None for database compatibility
    out_df = out_df.where(pd.notnull(out_df), None)
    tuples_to_insert = list(out_df.itertuples(index=False, name=None))

    return tuples_to_insert, total_rows, fallas_count


def iter_csv_telemetry_batches(file_path: str, filename: str, selected_buses: Optional[List[str]] = None,
                               chunksize: int = 50_000):
    """Parse a large CSV incrementally so its full contents never live in RAM."""
    allowed = {str(bus).strip().upper() for bus in (selected_buses or []) if str(bus).strip()}
    for frame in pd.read_csv(file_path, engine='c', low_memory=False, chunksize=chunksize):
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False)
        buffer.seek(0)
        yield parse_excel_or_csv_fast(buffer, filename, list(allowed))
