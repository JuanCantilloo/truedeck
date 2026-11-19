// TrueDeck Telemetría & Mapas - Frontend Client Logic

let map;
let markerClusterGroup;
let heatLayer = null;
let currentPoints = [];
let chartTopBuses = null;
let chartRangos = null;
let isHeatmapActive = false;

// Vehicle checkbox state
let allVehiclesList = [];          // full list from API
let selectedVehicles = new Set();  // codes currently checked
let vehiclePanelOpen = false;
let pendingUploadFiles = [];
let uploadPreviewBuses = [];
let uploadPreviewFiles = [];
let uploadPreviewErrors = [];
const RECENT_BUS_SEARCHES_KEY = 'truedeck.recentBusSearches';
let recentBusSearches = loadRecentBusSearches();
let busSearchTimer = null;

// Tile Layer URLs
const TILE_LAYERS = {
  carto: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
  cartoDark: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  osm: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  satellite: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
};
let activeBaseLayer;

document.addEventListener('DOMContentLoaded', () => {
  // Wire the controls first so a CDN failure in optional map/icon libraries
  // cannot leave the upload button and dialogs unresponsive.
  setupEventListeners();
  renderRecentBusSearches();

  try {
    window.lucide?.createIcons?.();
  } catch (err) {
    console.warn('Lucide icons could not be initialized:', err);
  }

  try {
    initMap();
  } catch (err) {
    console.error('Map could not be initialized:', err);
  }

  loadInitialData();
});

// 1. MAP INITIALIZATION
function initMap() {
  // Default to Bogotá coordinates
  const BOGOTA_COORDS = [4.60971, -74.08175];

  map = L.map('map', {
    center: BOGOTA_COORDS,
    zoom: 12,
    zoomControl: true,
    preferCanvas: true
  });

  activeBaseLayer = L.tileLayer(TILE_LAYERS.osm, {
    attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
    maxZoom: 19
  }).addTo(map);

  markerClusterGroup = L.markerClusterGroup({
    showCoverageOnHover: false,
    maxClusterRadius: 50,
    spiderfyOnMaxZoom: true,
    chunkedLoading: true,
    chunkInterval: 100,
    chunkDelay: 15,
    iconCreateFunction: function(cluster) {
      const markers = cluster.getAllChildMarkers();
      let hasError = false;
      for (let m of markers) {
        if (m.options.isError) {
          hasError = true;
          break;
        }
      }
      const count = cluster.getChildCount();
      const cClass = hasError ? 'bg-rose-600/90 ring-4 ring-rose-500/30' : 'bg-blue-600/90 ring-4 ring-blue-500/30';
      return L.divIcon({
        html: `<div class="flex items-center justify-center w-8 h-8 rounded-full text-white font-bold text-xs shadow-lg ${cClass}">${count}</div>`,
        className: 'custom-cluster-icon',
        iconSize: L.point(32, 32)
      });
    }
  });

  map.addLayer(markerClusterGroup);
}

// Custom Marker Pin HTML
function createPinIcon(isRetransmitted, latenciaMin) {
  let color = '#10b981'; // Green (Normal)
  let pulse = '';
  
  if (isRetransmitted) {
    color = '#f43f5e'; // Red (Falla / Retransmitida)
    pulse = '<span class="absolute -top-1 -right-1 w-2.5 h-2.5 bg-rose-400 rounded-full animate-ping"></span>';
  } else if (latenciaMin > 5) {
    color = '#f59e0b'; // Amber (Latencia moderada)
  }

  const svg = `
    <div class="relative flex items-center justify-center">
      ${pulse}
      <svg width="26" height="34" viewBox="0 0 24 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M12 0C5.37 0 0 5.37 0 12C0 21 12 32 12 32C12 32 24 21 24 12C24 5.37 18.63 0 12 0Z" fill="${color}" stroke="#0f172a" stroke-width="1.5"/>
        <circle cx="12" cy="12" r="5" fill="#ffffff" />
      </svg>
    </div>
  `;

  return L.divIcon({
    className: 'custom-pin-icon',
    html: svg,
    iconSize: [26, 34],
    iconAnchor: [13, 34],
    popupAnchor: [0, -32]
  });
}

// 2. EVENT LISTENERS
function setupEventListeners() {
  // Map Layer Change
  document.getElementById('selectMapLayer').addEventListener('change', (e) => {
    const val = e.target.value;
    map.removeLayer(activeBaseLayer);
    let url = TILE_LAYERS.osm;
    if (val === 'carto') url = TILE_LAYERS.carto;
    else if (val === 'satellite') url = TILE_LAYERS.satellite;
    activeBaseLayer = L.tileLayer(url, {
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
      maxZoom: 19
    }).addTo(map);
  });

  // Center Bogota
  document.getElementById('btnCenterBogota').addEventListener('click', () => {
    map.flyTo([4.60971, -74.08175], 12);
  });

  // Heatmap Toggle
  document.getElementById('btnToggleHeatmap').addEventListener('click', () => {
    isHeatmapActive = !isHeatmapActive;
    const btn = document.getElementById('btnToggleHeatmap');
    if (isHeatmapActive) {
      btn.classList.add('bg-amber-500/20', 'border-amber-500', 'text-amber-300');
      map.removeLayer(markerClusterGroup);
      renderHeatmap();
    } else {
      btn.classList.remove('bg-amber-500/20', 'border-amber-500', 'text-amber-300');
      if (heatLayer) map.removeLayer(heatLayer);
      map.addLayer(markerClusterGroup);
    }
  });

  const filterModal = document.getElementById('filterModal');
  const closeFilterModal = () => {
    filterModal.classList.add('hidden');
    filterModal.classList.remove('flex');
  };
  document.getElementById('btnOpenFilters').addEventListener('click', () => {
    filterModal.classList.remove('hidden');
    filterModal.classList.add('flex');
    document.getElementById('btnCloseFilters').focus();
  });
  document.getElementById('btnCloseFilters').addEventListener('click', closeFilterModal);
  filterModal.addEventListener('click', event => {
    if (event.target === filterModal) closeFilterModal();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !filterModal.classList.contains('hidden')) closeFilterModal();
  });

  // Filter Form Submit
  document.getElementById('filterForm').addEventListener('submit', (e) => {
    e.preventDefault();
    clearTimeout(busSearchTimer);
    fetchTelemetria(true);
    closeFilterModal();
  });

  // Apply bus-code searches as the user types, while keeping requests bounded.
  document.getElementById('filterBus').addEventListener('input', (e) => {
    const bus = e.target.value.trim();
    // Clear any checkbox selections when typing a custom code
    if (selectedVehicles.size) {
      selectedVehicles.clear();
      document.querySelectorAll('.vehicle-cb-item input[type=checkbox]').forEach(cb => { cb.checked = false; });
      updateVehicleBadge();
    }
    clearTimeout(busSearchTimer);
    if (bus.length === 0) {
      // no code typed, just reset filters
      busSearchTimer = setTimeout(() => fetchTelemetria(), 350);
    } else if (bus.length >= 1) {
      // auto-select this bus in the set for multi-vehicle fetching
      selectedVehicles.add(bus);
      // check corresponding checkbox if exists
      const checkbox = document.querySelector(`.vehicle-cb-item[data-code="${bus}"] input[type=checkbox]`);
      if (checkbox) checkbox.checked = true;
      updateVehicleBadge();
      busSearchTimer = setTimeout(() => fetchTelemetria(), 350);
    }
  });
  document.getElementById('filterBus').addEventListener('input', (e) => {
    const bus = e.target.value.trim();
    if (selectedVehicles.size) {
      selectedVehicles.clear();
      document.querySelectorAll('.vehicle-cb-item input[type=checkbox]').forEach(cb => { cb.checked = false; });
      updateVehicleBadge();
    }
    clearTimeout(busSearchTimer);
    if (bus.length === 0 || bus.length >= 2) {
      busSearchTimer = setTimeout(() => fetchTelemetria(), 350);
    }
  });

  // Limit & Solo Falla change trigger immediate filter
  document.getElementById('filterLimit').addEventListener('change', () => {
    fetchTelemetria();
  });
  document.getElementById('filterSoloRetransmitida').addEventListener('change', () => {
    fetchTelemetria();
  });

  // Reset Filters
  document.getElementById('btnResetFilters').addEventListener('click', () => {
    document.getElementById('filterForm').reset();
    selectedVehicles.clear();
    updateVehicleBadge();
    fetchTelemetria();
    closeFilterModal();
  });

  // ---- VEHICLE CHECKBOX PANEL LOGIC ----

  // Toggle panel open/close
  document.getElementById('btnToggleVehiclePanel').addEventListener('click', () => {
    vehiclePanelOpen = !vehiclePanelOpen;
    const panel = document.getElementById('vehicleCheckboxPanel');
    const chevron = document.getElementById('iconVehicleChevron');
    if (vehiclePanelOpen) {
      panel.classList.remove('hidden');
      chevron.style.transform = 'rotate(180deg)';
    } else {
      panel.classList.add('hidden');
      chevron.style.transform = 'rotate(0deg)';
    }
  });

  // Live search within checkbox grid
  document.getElementById('searchVehicleCheck').addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase();
    document.querySelectorAll('.vehicle-cb-item').forEach(item => {
      const code = item.dataset.code.toLowerCase();
      item.style.display = !q || code.includes(q) ? '' : 'none';
    });
  });

  // Select all visible
  document.getElementById('btnSelectAllVehicles').addEventListener('click', () => {
    document.querySelectorAll('.vehicle-cb-item').forEach(item => {
      if (item.style.display !== 'none') {
        const cb = item.querySelector('input[type=checkbox]');
        cb.checked = true;
        selectedVehicles.add(item.dataset.code);
      }
    });
    updateVehicleBadge();
  });

  // Deselect all
  document.getElementById('btnClearAllVehicles').addEventListener('click', () => {
    document.querySelectorAll('.vehicle-cb-item input[type=checkbox]').forEach(cb => {
      cb.checked = false;
    });
    selectedVehicles.clear();
    updateVehicleBadge();
  });

  // Apply selection as filter
  document.getElementById('btnApplyVehicleFilter').addEventListener('click', () => {
    fetchTelemetria();
    closeFilterModal();
  });

  // Upload Modal
  const modalUpload = document.getElementById('modalUpload');
  document.getElementById('btnOpenUploadModal').addEventListener('click', () => {
    pendingUploadFiles = [];
    uploadPreviewBuses = [];
    uploadPreviewFiles = [];
    uploadPreviewErrors = [];
    document.getElementById('uploadSelectionPanel').classList.add('hidden');
    document.getElementById('uploadBusList').innerHTML = '';
    document.getElementById('uploadFilesSummary').classList.add('hidden');
    document.getElementById('uploadStatus').classList.add('hidden');
    document.getElementById('uploadSpinner').classList.add('hidden');
    const progressBar = document.getElementById('uploadProgressBar');
    progressBar.style.width = '0%';
    progressBar.classList.remove('bg-emerald-500', 'bg-rose-500');
    progressBar.classList.add('bg-blue-500');
    document.getElementById('uploadProgressLabel').innerText = '0%';
    modalUpload.classList.remove('hidden');
  });
  document.getElementById('btnCloseUploadModal').addEventListener('click', () => {
    modalUpload.classList.add('hidden');
  });

  document.getElementById('btnSelectAllUploadBuses').addEventListener('click', () => {
    document.querySelectorAll('.upload-bus-option input[type=checkbox]').forEach(cb => cb.checked = true);
  });
  document.getElementById('btnClearUploadSelection').addEventListener('click', () => {
    document.querySelectorAll('.upload-bus-option input[type=checkbox]').forEach(cb => cb.checked = false);
  });
  document.getElementById('btnApplyUploadSelection').addEventListener('click', async () => {
    if (!pendingUploadFiles.length) return;
    const selected = getSelectedUploadBuses();
    await performUpload(selected);
  });

  // Drag and drop and file picker both use the preview and upload flow below.
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');

  dropZone.addEventListener('click', () => fileInput.click());
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('border-blue-500', 'bg-blue-500/10');
  });
  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('border-blue-500', 'bg-blue-500/10');
  });
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('border-blue-500', 'bg-blue-500/10');
    if (e.dataTransfer.files.length > 0) {
      handleFileUpload(Array.from(e.dataTransfer.files));
    }
  });
  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      handleFileUpload(Array.from(e.target.files));
      fileInput.value = '';
    }
  });

  // Export Excel
  document.getElementById('btnExportExcel').addEventListener('click', exportToExcel);

  // Clear data
  document.getElementById('btnClearData').addEventListener('click', async () => {
    if (confirm('¿Estás seguro de que deseas vaciar todos los registros cargados de la base de datos?')) {
      await fetch('/api/limpiar-datos', { method: 'DELETE' });
      loadInitialData();
    }
  });

  // Map Config Modal
  const modalMapConfig = document.getElementById('modalMapConfig');
  document.getElementById('btnOpenMapConfig').addEventListener('click', () => {
    modalMapConfig.classList.remove('hidden');
  });
  document.getElementById('btnCloseMapConfig').addEventListener('click', () => {
    modalMapConfig.classList.add('hidden');
  });
  document.getElementById('btnSaveMapConfig').addEventListener('click', () => {
    const key = document.getElementById('inputGoogleMapsKey').value.trim();
    if (key) {
      localStorage.setItem('google_maps_api_key', key);
      alert('Clave de Google Maps guardada. El mapa base libre está activo y listo para enlazar.');
    }
    modalMapConfig.classList.add('hidden');
  });
}

// 3. DATA FETCHING & API INTEGRATION
async function loadInitialData() {
  await fetchStats();
  await fetchVehiculosList();
  await fetchRutasList();
  await fetchTelemetria();
  await fetchMetricas();
}

async function fetchStats() {
  try {
    const res = await fetch('/api/stats-resumen');
    const data = await res.json();
    document.getElementById('statTotal').innerText = data.totalRegistros.toLocaleString();
    document.getElementById('statFallas').innerText = data.totalConFalla.toLocaleString();
    document.getElementById('statTasa').innerText = `${data.tasaFallaPorcentaje}%`;
    document.getElementById('statVehiculos').innerText = data.totalVehiculos.toLocaleString();
    document.getElementById('statArchivos').innerText = data.totalArchivos.toLocaleString();
  } catch (err) {
    console.error('Error fetching stats:', err);
  }
}

async function fetchVehiculosList() {
  try {
    const res = await fetch('/api/vehiculos');
    const buses = await res.json();
    allVehiclesList = buses;

    // Update datalist for text input autocomplete
    const datalist = document.getElementById('listVehiculos');
    datalist.innerHTML = '';
    buses.forEach(b => {
      const opt = document.createElement('option');
      opt.value = b;
      datalist.appendChild(opt);
    });

    // Populate checkbox grid
    renderVehicleCheckboxGrid(buses);

    // Update count label
    const lbl = document.getElementById('lblVehicleCount');
    if (lbl) lbl.innerText = `${buses.length} vehículos disponibles`;
  } catch (err) {
    console.error('Error fetching vehicles:', err);
  }
}

function renderVehicleCheckboxGrid(buses) {
  const grid = document.getElementById('vehicleCheckboxGrid');
  if (!grid) return;
  grid.innerHTML = '';

  if (!buses || buses.length === 0) {
    grid.innerHTML = '<p class="col-span-full text-xs text-slate-500 text-center py-4">No hay vehículos cargados aún.</p>';
    return;
  }

  buses.forEach(code => {
    const isChecked = selectedVehicles.has(code);
    const item = document.createElement('label');
    item.className = 'vehicle-cb-item flex items-center gap-1.5 cursor-pointer select-none group bg-slate-950 hover:bg-slate-800 border border-slate-800 hover:border-indigo-500/40 rounded-lg px-2 py-1.5 transition';
    item.dataset.code = code;
    item.innerHTML = `
      <input type="checkbox" class="vehicle-cb w-3.5 h-3.5 rounded bg-slate-800 border-slate-600 text-indigo-500 focus:ring-0 cursor-pointer shrink-0" ${isChecked ? 'checked' : ''}>
      <span class="text-[11px] font-mono text-slate-300 group-hover:text-white truncate" title="${code}">${code}</span>
    `;
    item.querySelector('input').addEventListener('change', (e) => {
      if (e.target.checked) {
        selectedVehicles.add(code);
      } else {
        selectedVehicles.delete(code);
      }
      updateVehicleBadge();
    });
    grid.appendChild(item);
  });
}

function updateVehicleBadge() {
  const badge = document.getElementById('badgeVehiculosSelected');
  if (!badge) return;
  const count = selectedVehicles.size;
  const topBadge = document.getElementById('badgeVehiculosSelectedTop');
  if (topBadge) {
    topBadge.textContent = `${count} bus${count === 1 ? '' : 'es'}`;
    topBadge.classList.toggle('hidden', count === 0);
  }
  if (count > 0) {
    badge.classList.remove('hidden');
    badge.innerText = `${count} seleccionado${count > 1 ? 's' : ''}`;
  } else {
    badge.classList.add('hidden');
  }
}

async function fetchRutasList() {
  try {
    const res = await fetch('/api/rutas');
    const rutas = await res.json();
    const select = document.getElementById('filterRuta');
    select.innerHTML = '<option value="">Todas las rutas</option>';
    rutas.forEach(r => {
      const opt = document.createElement('option');
      opt.value = r;
      opt.innerText = r;
      select.appendChild(opt);
    });
  } catch (err) {
    console.error('Error fetching routes:', err);
  }
}

async function fetchTelemetria(recordSearch = false) {
  const bus = document.getElementById('filterBus').value.trim();
  const ruta = document.getElementById('filterRuta').value.trim();
  const rangoLat = document.getElementById('filterRangoLatencia').value.trim();
  const soloFalla = document.getElementById('filterSoloRetransmitida').checked;
  const fInicio = document.getElementById('filterFechaInicio').value;
  const fFin = document.getElementById('filterFechaFin').value;

  const limitEl = document.getElementById('filterLimit');
  const limitVal = limitEl ? limitEl.value : '0';

  if (bus && recordSearch) {
    rememberBusSearch(bus);
  }

  // If checkboxes have a selection, fetch each selected vehicle in parallel and merge
  if (!bus && selectedVehicles.size > 0) {
    await fetchTelemetriaMultiVehiculo(
      [...selectedVehicles], ruta, rangoLat, soloFalla, fInicio, fFin, limitVal
    );
    return;
  }

  const params = new URLSearchParams();
  if (bus) params.append('idVehiculo', bus);
  if (ruta) params.append('idRuta', ruta);
  if (rangoLat) params.append('rangoLatencia', rangoLat);
  if (soloFalla) params.append('soloRetransmitida', 'true');
  if (fInicio) params.append('fechaInicio', fInicio);
  if (fFin) params.append('fechaFin', fFin);
  if (limitVal && limitVal !== '0') params.append('limit', limitVal);

  try {
    const res = await fetch(`/api/telemetria?${params.toString()}`);
    const data = await res.json();
    currentPoints = data.items || [];
    renderMarkers(currentPoints);
    renderTable(currentPoints);
    document.getElementById('lblTableSummary').innerText = `Mostrando ${currentPoints.length.toLocaleString()} de ${data.total.toLocaleString()} registros coincidentes`;
  } catch (err) {
    console.error('Error fetching telemetria:', err);
  }
}

function loadRecentBusSearches() {
  try {
    const stored = JSON.parse(localStorage.getItem(RECENT_BUS_SEARCHES_KEY) || '[]');
    return Array.isArray(stored) ? stored.filter(value => typeof value === 'string').slice(0, 8) : [];
  } catch (err) {
    console.warn('Could not load recent bus searches:', err);
    return [];
  }
}

function rememberBusSearch(bus) {
  const code = bus.trim();
  if (!code) return;
  recentBusSearches = [code, ...recentBusSearches.filter(item => item.toLowerCase() !== code.toLowerCase())].slice(0, 8);
  try {
    localStorage.setItem(RECENT_BUS_SEARCHES_KEY, JSON.stringify(recentBusSearches));
  } catch (err) {
    console.warn('Could not save recent bus searches:', err);
  }
  renderRecentBusSearches();
}

function renderRecentBusSearches() {
  const container = document.getElementById('recentBusSearches');
  if (!container) return;
  container.replaceChildren();
  if (recentBusSearches.length) {
    const label = document.createElement('span');
    label.className = 'text-[10px] text-slate-500 self-center';
    label.textContent = 'Recientes:';
    container.appendChild(label);
  }
  recentBusSearches.forEach(code => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'px-1.5 py-0.5 rounded bg-slate-800 hover:bg-indigo-600/40 border border-slate-700 text-[10px] font-mono text-slate-300 hover:text-white transition';
    button.textContent = code;
    button.title = `Buscar bus ${code}`;
    button.addEventListener('click', () => {
      document.getElementById('filterBus').value = code;
      selectedVehicles.clear();
      document.querySelectorAll('.vehicle-cb-item input[type=checkbox]').forEach(cb => { cb.checked = false; });
      updateVehicleBadge();
      fetchTelemetria(true);
    });
    container.appendChild(button);
  });
}

async function fetchTelemetriaMultiVehiculo(codes, ruta, rangoLat, soloFalla, fInicio, fFin, limitVal) {
  const fetches = codes.map(code => {
    const params = new URLSearchParams();
    params.append('idVehiculo', code);
    if (ruta) params.append('idRuta', ruta);
    if (rangoLat) params.append('rangoLatencia', rangoLat);
    if (soloFalla) params.append('soloRetransmitida', 'true');
    if (fInicio) params.append('fechaInicio', fInicio);
    if (fFin) params.append('fechaFin', fFin);
    return fetch(`/api/telemetria?${params.toString()}`).then(r => r.json());
  });

  try {
    const results = await Promise.all(fetches);
    let merged = [];
    let totalCount = 0;
    results.forEach(data => {
      merged = merged.concat(data.items || []);
      totalCount += data.total || 0;
    });
    // Sort: errors first, then by latency desc
    merged.sort((a, b) => {
      if (b.tramaRetransmitida !== a.tramaRetransmitida) return b.tramaRetransmitida ? 1 : -1;
      return b.latenciaMinutos - a.latenciaMinutos;
    });
    currentPoints = merged;
    renderMarkers(currentPoints);
    renderTable(currentPoints);
    document.getElementById('lblTableSummary').innerText = `${currentPoints.length.toLocaleString()} registros de ${codes.length} vehículos seleccionados`;
  } catch (err) {
    console.error('Error fetching multi-vehicle telemetria:', err);
  }
}

// 4. MAP RENDERING
function renderMarkers(items) {
  markerClusterGroup.clearLayers();
  if (heatLayer) map.removeLayer(heatLayer);

  const bounds = [];
  const locations = new Map();
  items.forEach(item => {
    if (item.latitud == null || item.longitud == null) return;
    const lat = Number(item.latitud);
    const lng = Number(item.longitud);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    // GPS jitter below one meter is treated as the same reported location.
    const key = `${lat.toFixed(6)},${lng.toFixed(6)}`;
    if (!locations.has(key)) locations.set(key, { lat, lng, records: [], errors: 0 });
    const location = locations.get(key);
    location.records.push(item);
    if (item.tramaRetransmitida === true) location.errors += 1;
  });

  locations.forEach(location => {
    const latLng = [location.lat, location.lng];
    bounds.push(latLng);
    const count = location.records.length;
    const icon = count > 1
      ? L.divIcon({
          className: 'coordinate-group-icon',
          html: `<div style="width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-weight:700;font-size:12px;border:2px solid #0f172a;background:${location.errors ? '#e11d48' : '#2563eb'};box-shadow:0 2px 10px #0009">${count.toLocaleString()}</div>`,
          iconSize: [38, 38],
          iconAnchor: [19, 19]
        })
      : createPinIcon(location.records[0].tramaRetransmitida === true, location.records[0].latenciaMinutos);
    const marker = L.marker(latLng, { icon, isError: location.errors > 0, recordCount: count });
    marker.bindPopup(() => buildLocationPopup(location), { maxWidth: 380, minWidth: 260 });
    markerClusterGroup.addLayer(marker);
  });
  document.getElementById('badgePuntosCount').innerText =
    `${items.length.toLocaleString()} registros · ${locations.size.toLocaleString()} ubicaciones`;

  if (isHeatmapActive) {
    renderHeatmap();
  } else if (bounds.length > 0) {
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
  }
}

function buildLocationPopup(location) {
  const root = document.createElement('div');
  root.className = 'text-xs font-sans';
  const heading = document.createElement('div');
  heading.className = 'font-bold text-sm text-white border-b border-slate-700 pb-2 mb-2';
  heading.textContent = `${location.records.length.toLocaleString()} registro(s) en ${location.lat.toFixed(6)}, ${location.lng.toFixed(6)}`;
  root.appendChild(heading);

  const list = document.createElement('div');
  list.style.maxHeight = '280px';
  list.style.overflowY = 'auto';
  list.className = 'space-y-2';
  location.records.forEach(item => {
    const entry = document.createElement('div');
    entry.className = 'border-b border-slate-700 pb-2 text-slate-300';
    const bus = document.createElement('div');
    bus.className = 'flex items-center justify-between gap-2 font-bold text-white';
    const busName = document.createElement('span');
    busName.textContent = `🚌 ${item.idVehiculo || 'Bus desconocido'}`;
    const state = document.createElement('span');
    state.className = item.tramaRetransmitida ? 'text-rose-400' : 'text-emerald-400';
    state.textContent = item.tramaRetransmitida ? 'Descuadre' : 'Normal';
    bus.append(busName, state);
    const details = document.createElement('div');
    details.className = 'mt-1 text-[11px]';
    details.textContent = `Ruta: ${item.idRuta || 'N/D'} · Lectura: ${formatDateStr(item.fechaHoraLecturaDato)} · Latencia: ${Number(item.latenciaMinutos || 0).toFixed(1)} min`;
    const filter = document.createElement('button');
    filter.className = 'mt-1 text-blue-400 hover:text-blue-300';
    filter.textContent = 'Filtrar este bus';
    filter.addEventListener('click', () => window.filterByBus(item.idVehiculo));
    entry.append(bus, details, filter);
    list.appendChild(entry);
  });
  root.appendChild(list);
  return root;
}

function renderHeatmap() {
  if (heatLayer) map.removeLayer(heatLayer);
  const heatByLocation = new Map();
  currentPoints.forEach(p => {
    if (p.latitud == null || p.longitud == null) return;
    const lat = Number(p.latitud);
    const lng = Number(p.longitud);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    const key = `${lat.toFixed(6)},${lng.toFixed(6)}`;
    const intensity = p.tramaRetransmitida ? 1.0 : (p.latenciaMinutos > 5 ? 0.6 : 0.2);
    heatByLocation.set(key, { lat, lng, intensity: Math.min(1, (heatByLocation.get(key)?.intensity || 0) + intensity) });
  });
  const heatPoints = [...heatByLocation.values()].map(p => [p.lat, p.lng, p.intensity]);

  heatLayer = L.heatLayer(heatPoints, {
    radius: 25,
    blur: 18,
    maxZoom: 16,
    gradient: { 0.2: '#3b82f6', 0.5: '#eab308', 0.8: '#f97316', 1.0: '#ef4444' }
  }).addTo(map);
}

// 5. DATA TABLE RENDERING
function renderTable(items) {
  const tbody = document.getElementById('tableBody');
  tbody.innerHTML = '';

  if (items.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="text-center py-8 text-slate-500">
          No se encontraron registros con los filtros seleccionados.
        </td>
      </tr>
    `;
    return;
  }

  items.slice(0, 100).forEach(item => {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-slate-800/50 transition';

    const hasCoords = item.latitud != null && item.longitud != null;
    const isError = item.tramaRetransmitida === true;

    tr.innerHTML = `
      <td class="p-2 font-semibold text-white flex items-center gap-1">
        ${isError ? '<span class="w-2 h-2 rounded-full bg-rose-500 inline-block"></span>' : ''}
        ${item.idVehiculo}
      </td>
      <td class="p-2 text-slate-400">${item.idRuta || '-'}</td>
      <td class="p-2 text-slate-300 text-[11px]">${formatDateStr(item.fechaHoraLecturaDato)}</td>
      <td class="p-2 ${item.latenciaMinutos > 30 ? 'text-rose-400 font-bold' : (item.latenciaMinutos > 5 ? 'text-amber-400 font-semibold' : 'text-slate-400')}">
        ${item.latenciaMinutos > 60 ? (item.latenciaMinutos/60).toFixed(1) + ' hrs' : item.latenciaMinutos.toFixed(1) + ' min'}
      </td>
      <td class="p-2 text-center">
        ${isError 
          ? '<span class="px-1.5 py-0.5 bg-rose-500/20 text-rose-400 border border-rose-500/30 rounded text-[10px] font-bold">TRUE</span>'
          : '<span class="text-slate-500 text-[10px]">false</span>'}
      </td>
      <td class="p-2 text-center">
        ${hasCoords 
          ? `<button onclick="flyToPoint(${item.latitud}, ${item.longitud})" class="p-1 hover:bg-slate-700 text-blue-400 rounded transition" title="Ver en mapa">
               📍
             </button>`
          : '<span class="text-slate-600 text-[10px]">Sin GPS</span>'}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

window.flyToPoint = function(lat, lng) {
  document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });
  map.flyTo([lat, lng], 16, { animate: true, duration: 1.2 });
};

window.filterByBus = function(busCode) {
  // Clear checkbox selection, set text input, close popup
  selectedVehicles.clear();
  document.querySelectorAll('.vehicle-cb-item input[type=checkbox]').forEach(cb => { cb.checked = false; });
  updateVehicleBadge();
  document.getElementById('filterBus').value = busCode;
  map.closePopup();
  fetchTelemetria();
};

// 6. METRICS & CHARTS
async function fetchMetricas() {
  try {
    const fInicio = document.getElementById('filterFechaInicio').value;
    const fFin = document.getElementById('filterFechaFin').value;
    const params = new URLSearchParams();
    if (fInicio) params.append('fechaInicio', fInicio);
    if (fFin) params.append('fechaFin', fFin);

    const res = await fetch(`/api/metricas?${params.toString()}`);
    const data = await res.json();

    renderTopBusesChart(data.topVehiculos);
    renderRangosChart(data.rangosDistribucion);
  } catch (err) {
    console.error('Error fetching metrics:', err);
  }
}

function renderTopBusesChart(topVehiculos) {
  const ctx = document.getElementById('chartTopBuses').getContext('2d');
  if (chartTopBuses) chartTopBuses.destroy();

  const labels = topVehiculos.map(v => v.idVehiculo);
  const fallas = topVehiculos.map(v => v.totalFallas);

  chartTopBuses = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Descuadres (true)',
        data: fallas,
        backgroundColor: '#f43f5e',
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false }
      },
      scales: {
        x: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { display: false } },
        y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: '#334155' } }
      }
    }
  });
}

function renderRangosChart(rangos) {
  const ctx = document.getElementById('chartRangos').getContext('2d');
  if (chartRangos) chartRangos.destroy();

  const labels = rangos.map(r => r.rango);
  const totals = rangos.map(r => r.total);

  chartRangos = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: totals,
        backgroundColor: ['#10b981', '#3b82f6', '#f59e0b', '#f97316', '#ef4444', '#64748b'],
        borderWidth: 1,
        borderColor: '#0f172a'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'right',
          labels: { color: '#cbd5e1', font: { size: 10 }, boxWidth: 12 }
        }
      }
    }
  });
}

function normalizeBusCode(raw) {
  if (raw === null || raw === undefined) return null;
  const str = String(raw).trim();
  if (!str || str.toLowerCase() === 'nan' || str.toLowerCase() === 'none' || str.toLowerCase() === 'null') return null;
  return str.toUpperCase();
}

function getSelectedUploadBuses() {
  return [...document.querySelectorAll('.upload-bus-option input[type=checkbox]:checked')].map(cb => cb.value);
}

function createUploadId() {
  if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return Array.from(bytes, (byte, index) => {
    const hex = byte.toString(16).padStart(2, '0');
    return [4, 6, 8, 10].includes(index) ? `-${hex}` : hex;
  }).join('');
}

async function readUploadResponse(response) {
  const text = await response.text();
  try {
    return text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`Respuesta no válida del servidor (HTTP ${response.status})`);
  }
}

function updatePreviewProgress(percent, message) {
  const statusBox = document.getElementById('uploadStatus');
  const progressBar = document.getElementById('uploadProgressBar');
  const progressLabel = document.getElementById('uploadProgressLabel');
  statusBox.classList.remove('hidden');
  document.getElementById('uploadSpinner').classList.remove('hidden');
  document.getElementById('uploadStatusText').innerText = message;
  progressBar.classList.remove('bg-emerald-500', 'bg-rose-500');
  progressBar.classList.add('bg-blue-500');
  progressBar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  progressLabel.innerText = `${Math.floor(percent)}%`;
}

function readFileAsArrayBuffer(file, onProgress) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onprogress = event => {
      if (event.lengthComputable) onProgress(event.loaded);
    };
    reader.onerror = () => reject(reader.error || new Error('No se pudo leer el archivo'));
    reader.onabort = () => reject(new Error('Lectura cancelada'));
    reader.onload = () => {
      onProgress(file.size);
      resolve(reader.result);
    };
    reader.readAsArrayBuffer(file);
  });
}

async function previewUploadBuses(files) {
  const filePreviews = [];
  const errors = [];

  for (const [index, file] of files.entries()) {
    const fileLabel = `Archivo ${index + 1}/${files.length}: ${file.name}`;
    const reportReadProgress = loaded => {
      const fraction = file.size ? Math.min(1, loaded / file.size) : 1;
      const percent = ((index + 0.9 * fraction) / files.length) * 100;
      updatePreviewProgress(percent, `Leyendo ${fileLabel}`);
    };
    reportReadProgress(0);
    try {
      let buses;
      if (/\.csv$/i.test(file.name)) {
        buses = await scanCsvBusCodes(file, reportReadProgress);
      } else {
        const arrayBuffer = await readFileAsArrayBuffer(file, reportReadProgress);
        updatePreviewProgress(
          ((index + 0.9) / files.length) * 100,
          `Analizando ${fileLabel}`,
        );
        // Let Safari paint the progress message before XLSX parses the workbook.
        await new Promise(resolve => requestAnimationFrame(resolve));
        const workbook = XLSX.read(arrayBuffer, { type: 'array', cellDates: true });
        const sheet = workbook.Sheets[workbook.SheetNames[0]];
        const rows = XLSX.utils.sheet_to_json(sheet, { defval: null, raw: false });
        buses = rows.map(row => normalizeBusCode(row.idVehiculo ?? row.id_vehiculo ?? row.vehiculo ?? row.bus ?? row.codigo_bus ?? row.codigoBus ?? row['ID Vehiculo'])).filter(Boolean);
      }
      buses = Array.from(new Set(buses)).sort((a, b) => a.localeCompare(b));

      if (buses.length) {
        filePreviews.push({ file, buses });
      } else {
        errors.push(`${file.name}: no se detectaron buses válidos`);
      }
    } catch (err) {
      console.error(`Error previewing ${file.name}:`, err);
      errors.push(`${file.name}: no se pudo leer para detectar buses`);
    }
    updatePreviewProgress(
      ((index + 1) / files.length) * 100,
      `Revisión ${index + 1}/${files.length} completada`,
    );
  }

  const buses = Array.from(new Set(filePreviews.flatMap(item => item.buses)))
    .sort((a, b) => a.localeCompare(b));
  uploadPreviewFiles = filePreviews;
  uploadPreviewBuses = buses;
  uploadPreviewErrors = errors;

  const list = document.getElementById('uploadBusList');
  const panel = document.getElementById('uploadSelectionPanel');
  const summary = document.getElementById('uploadSelectionSummary');
  list.innerHTML = '';

  buses.forEach(code => {
    const label = document.createElement('label');
    label.className = 'upload-bus-option flex items-center gap-2 px-2 py-1.5 rounded-lg border border-slate-700 bg-slate-900 hover:border-blue-500/50 cursor-pointer';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = code;
    checkbox.checked = true;
    checkbox.className = 'w-3.5 h-3.5 rounded text-blue-500 bg-slate-800 border-slate-600 focus:ring-0';
    const name = document.createElement('span');
    name.className = 'text-[11px] font-mono text-slate-200';
    name.textContent = code;
    label.append(checkbox, name);
    list.appendChild(label);
  });

  if (buses.length) {
    panel.classList.remove('hidden');
    summary.textContent = `${files.length} archivos · ${buses.length} buses detectados${errors.length ? ` · ${errors.length} archivo(s) sin vista previa` : ''}`;
  } else {
    panel.classList.add('hidden');
  }
  return buses;
}

function scanCsvBusCodes(file, onProgress = () => {}) {
  return new Promise((resolve, reject) => {
    let worker;
    try {
      worker = new Worker(new URL('./csv-preview-worker.js', import.meta.url), { type: 'module' });
    } catch (err) {
      reject(err);
      return;
    }

    worker.onmessage = event => {
      const message = event.data || {};
      if (message.type === 'progress') {
        onProgress(message.loaded);
      } else if (message.type === 'complete') {
        worker.terminate();
        resolve(message.buses || []);
      } else if (message.type === 'error') {
        worker.terminate();
        reject(new Error(message.message || 'No se pudo analizar el CSV'));
      }
    };
    worker.onerror = event => {
      worker.terminate();
      reject(new Error(event.message || 'Falló el análisis del CSV'));
    };
    worker.postMessage({ file });
  });
}

// 7. FILE UPLOAD HANDLING
async function handleFileUpload(files) {
  if (!files || !files.length) return;
  pendingUploadFiles = Array.from(files);
  const statusBox = document.getElementById('uploadStatus');
  const statusText = document.getElementById('uploadStatusText');
  const progressBar = document.getElementById('uploadProgressBar');
  const progressLabel = document.getElementById('uploadProgressLabel');

  statusBox.classList.remove('hidden');
  document.getElementById('uploadSpinner').classList.remove('hidden');
  statusText.innerText = `Preparando ${pendingUploadFiles.length} archivo(s)…`;
  document.getElementById('uploadFilesSummary').textContent =
    `${pendingUploadFiles.length} archivo(s): ${pendingUploadFiles.map(file => file.name).join(', ')}`;
  document.getElementById('uploadFilesSummary').classList.remove('hidden');
  if (progressBar) { progressBar.style.width = '0%'; progressBar.classList.replace('bg-emerald-500', 'bg-blue-500'); }
  if (progressLabel) progressLabel.innerText = '0%';

  const buses = await previewUploadBuses(pendingUploadFiles);
  if (!buses.length) {
    statusBox.classList.remove('hidden');
    document.getElementById('uploadSpinner').classList.add('hidden');
    statusText.innerText = `❌ No se detectaron buses válidos. ${uploadPreviewErrors.join('; ')}`;
    if (progressBar) {
      progressBar.style.width = '100%';
      progressBar.classList.remove('bg-blue-500', 'bg-emerald-500');
      progressBar.classList.add('bg-rose-500');
    }
    if (progressLabel) progressLabel.innerText = '100%';
    return;
  }

  document.getElementById('uploadSpinner').classList.add('hidden');
  statusText.innerText = `📄 Lectura lista: ${pendingUploadFiles.length}/${pendingUploadFiles.length} archivos revisados. Selecciona los buses que quieres cargar.`;
  statusBox.classList.remove('hidden');
  if (progressBar) {
    progressBar.style.width = '100%';
    progressBar.classList.remove('bg-blue-500', 'bg-rose-500');
    progressBar.classList.add('bg-emerald-500');
  }
  if (progressLabel) progressLabel.innerText = '100%';
}

async function performUpload(selectedBuses = []) {
  const statusBox = document.getElementById('uploadStatus');
  const statusText = document.getElementById('uploadStatusText');
  const progressBar = document.getElementById('uploadProgressBar');
  const progressLabel = document.getElementById('uploadProgressLabel');
  const submitButton = document.getElementById('btnApplyUploadSelection');

  if (!selectedBuses || !selectedBuses.length) {
    statusBox.classList.remove('hidden');
    statusText.innerText = '❌ Debes seleccionar al menos un bus antes de cargar.';
    if (progressBar) { progressBar.style.width = '100%'; progressBar.classList.replace('bg-blue-500', 'bg-rose-500'); }
    if (progressLabel) progressLabel.innerText = '100%';
    return;
  }

  const selected = new Set(selectedBuses.map(code => code.toUpperCase()));
  const filesToUpload = uploadPreviewFiles.filter(item =>
    item.buses.some(code => selected.has(code.toUpperCase()))
  );
  const skippedCount = uploadPreviewFiles.length - filesToUpload.length;
  if (!filesToUpload.length) {
    statusBox.classList.remove('hidden');
    statusText.innerText = '❌ Ninguno de los buses seleccionados está presente en los archivos.';
    if (progressBar) { progressBar.style.width = '100%'; progressBar.classList.replace('bg-blue-500', 'bg-rose-500'); }
    if (progressLabel) progressLabel.innerText = '100%';
    return;
  }

  statusBox.classList.remove('hidden');
  submitButton.disabled = true;
  submitButton.classList.add('opacity-60', 'cursor-not-allowed');
  document.getElementById('uploadSpinner').classList.remove('hidden');
  if (progressBar) {
    progressBar.style.width = '0%';
    progressBar.classList.remove('bg-rose-500', 'bg-emerald-500');
    progressBar.classList.add('bg-blue-500');
  }
  let successfulFiles = 0;
  let totalRows = 0;
  let totalFailures = 0;
  const uploadErrors = [...uploadPreviewErrors];
  const chunkSize = 8 * 1024 * 1024;
  const totalChunks = filesToUpload.reduce(
    (total, item) => total + Math.max(1, Math.ceil(item.file.size / chunkSize)),
    0
  );
  let uploadedChunks = 0;

  try {
    for (const [index, item] of filesToUpload.entries()) {
      const fileBuses = item.buses.filter(code => selected.has(code.toUpperCase()));
      const uploadId = createUploadId();
      const fileChunkCount = Math.max(1, Math.ceil(item.file.size / chunkSize));
      try {
        for (let chunkIndex = 0; chunkIndex < fileChunkCount; chunkIndex += 1) {
          const start = chunkIndex * chunkSize;
          const chunkBlob = item.file.slice(start, Math.min(start + chunkSize, item.file.size));
          const chunkForm = new FormData();
          chunkForm.append('upload_id', uploadId);
          chunkForm.append('chunk_index', String(chunkIndex));
          chunkForm.append('total_chunks', String(fileChunkCount));
          chunkForm.append('chunk', chunkBlob, 'chunk.part');

          statusText.innerText =
            `📤 Archivo ${index + 1}/${filesToUpload.length}: ${item.file.name} ` +
            `(fragmento ${chunkIndex + 1}/${fileChunkCount})`;
          const chunkResponse = await fetch('/api/upload/chunk', { method: 'POST', body: chunkForm });
          const chunkResult = await readUploadResponse(chunkResponse);
          if (!chunkResponse.ok || chunkResult.success !== true) {
            throw new Error(chunkResult.detail || `el servidor respondió HTTP ${chunkResponse.status}`);
          }

          uploadedChunks += 1;
          if (progressBar) {
            const percent = Math.floor((uploadedChunks / totalChunks) * 90);
            progressBar.style.width = `${percent}%`;
            progressLabel.innerText = `${percent}%`;
          }
        }

        statusText.innerText = `⚙️ Procesando y guardando ${index + 1}/${filesToUpload.length}: ${item.file.name}`;
        const completeForm = new FormData();
        completeForm.append('upload_id', uploadId);
        completeForm.append('filename', item.file.name);
        completeForm.append('total_chunks', String(fileChunkCount));
        completeForm.append('buses', JSON.stringify(fileBuses));

        const response = await fetch('/api/upload/complete', { method: 'POST', body: completeForm });
        const result = await readUploadResponse(response);
        if (!response.ok || result.success !== true) {
          throw new Error(result.detail || `el servidor respondió HTTP ${response.status}`);
        }
        successfulFiles += 1;
        totalRows += result.registrosImportados || 0;
        totalFailures += result.totalConFalla || 0;
      } catch (err) {
        uploadErrors.push(`${item.file.name}: ${err.message}`);
        try {
          await fetch(`/api/upload/chunk/${encodeURIComponent(uploadId)}`, { method: 'DELETE' });
        } catch (cleanupError) {
          console.warn(`Could not clean up upload fragments for ${item.file.name}:`, cleanupError);
        }
      }
    }
  } finally {
    submitButton.disabled = false;
    submitButton.classList.remove('opacity-60', 'cursor-not-allowed');
  }

  if (progressBar) {
    progressBar.style.width = '100%';
    progressLabel.innerText = '100%';
    progressBar.classList.remove('bg-blue-500', 'bg-emerald-500', 'bg-rose-500');
    progressBar.classList.add(uploadErrors.length ? 'bg-rose-500' : 'bg-emerald-500');
  }
  document.getElementById('uploadSpinner').classList.add('hidden');
  statusText.innerText =
    `${uploadErrors.length ? '⚠️ Carga finalizada con novedades' : '✅ Carga finalizada'}: ` +
    `${successfulFiles}/${filesToUpload.length} archivo(s), ${totalRows.toLocaleString()} registros, ` +
    `${totalFailures.toLocaleString()} con descuadre` +
    `${skippedCount ? `, ${skippedCount} omitido(s) sin buses seleccionados` : ''}` +
    `${uploadErrors.length ? `\n${uploadErrors.join('\n')}` : ''}`;
  if (successfulFiles) loadInitialData();

  if (!uploadErrors.length) {
    setTimeout(() => {
      document.getElementById('modalUpload').classList.add('hidden');
      statusBox.classList.add('hidden');
      if (progressBar) { progressBar.style.width = '0%'; progressBar.classList.replace('bg-emerald-500', 'bg-blue-500'); }
    }, 2500);
  }
}

// 8. EXCEL EXPORT
function exportToExcel() {
  if (currentPoints.length === 0) {
    alert('No hay datos filtrados para exportar.');
    return;
  }

  const exportData = currentPoints.map(p => ({
    "idVehiculo": p.idVehiculo,
    "idRuta": p.idRuta,
    "fechaHoraLecturaDato": p.fechaHoraLecturaDato,
    "fechaHoraEnvioDato": p.fechaHoraEnvioDato,
    "latenciaMinutos": p.latenciaMinutos,
    "RangoLatencia": p.RangoLatencia,
    "tramaRetransmitida": p.tramaRetransmitida ? 'true' : 'false',
    "latitud": p.latitud,
    "longitud": p.longitud,
    "velocidadVehiculo": p.velocidadVehiculo,
    "archivoOrigen": p.archivoOrigen
  }));

  const worksheet = XLSX.utils.json_to_sheet(exportData);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, worksheet, "Telemetría");
  XLSX.writeFile(workbook, `reporte_telemetria_${Date.now()}.xlsx`);
}

function formatDateStr(isoStr) {
  if (!isoStr) return '-';
  try {
    const d = new Date(isoStr);
    return d.toLocaleString('es-CO', {
      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
  } catch (e) {
    return isoStr;
  }
}
