function normalizeHeader(value) {
  return value.replace(/^\uFEFF/, '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function parseCsvFields(line) {
  const fields = [];
  let field = '';
  let quoted = false;

  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        field += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === ',' && !quoted) {
      fields.push(field.trim());
      field = '';
    } else {
      field += character;
    }
  }
  fields.push(field.trim());
  return fields;
}

function readCsvField(line, targetColumn) {
  let column = 0;
  let quoted = false;
  let field = '';

  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        if (column === targetColumn) field += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === ',' && !quoted) {
      if (column === targetColumn) return field.trim();
      column += 1;
      field = '';
    } else if (column === targetColumn) {
      field += character;
    }
  }
  return column === targetColumn ? field.trim() : '';
}

self.onmessage = async event => {
  const file = event.data?.file;
  if (!file) {
    self.postMessage({ type: 'error', message: 'No se recibió el archivo CSV' });
    return;
  }

  try {
    const reader = file.stream().getReader();
    const decoder = new TextDecoder('utf-8');
    const buses = new Set();
    let pending = '';
    let bytesRead = 0;
    let lastReportedBytes = 0;
    let busColumn = -1;
    let hasHeader = false;

    const processLine = line => {
      if (!hasHeader) {
        hasHeader = true;
        const headers = parseCsvFields(line).map(normalizeHeader);
        busColumn = headers.findIndex(value =>
          ['idvehiculo', 'vehiculo', 'bus', 'codigobus'].includes(value)
        );
        if (busColumn < 0) throw new Error('No se encontró la columna idVehiculo');
        return;
      }

      const code = readCsvField(line, busColumn).toUpperCase();
      if (code && !['NAN', 'NONE', 'NULL'].includes(code)) buses.add(code);
    };

    while (true) {
      const { value, done } = await reader.read();
      if (value) {
        bytesRead += value.byteLength;
        pending += decoder.decode(value, { stream: true });
      }
      if (done) pending += decoder.decode();

      const lines = pending.split(/\r?\n/);
      pending = lines.pop() || '';
      for (const line of lines) processLine(line);

      if (bytesRead - lastReportedBytes >= 512 * 1024 || done) {
        self.postMessage({ type: 'progress', loaded: bytesRead });
        lastReportedBytes = bytesRead;
      }
      if (done) break;
    }

    if (pending) processLine(pending);
    if (!hasHeader) throw new Error('El archivo CSV está vacío');
    self.postMessage({ type: 'complete', buses: [...buses] });
  } catch (error) {
    self.postMessage({ type: 'error', message: error.message || 'No se pudo analizar el CSV' });
  }
};
