/* ===== CONFIG ===== */

const FIELD_LAT = 21.004653740330102;
const FIELD_LON = 79.04782475333111;
const GAUGE_MAX_MM = 40;
const REFRESH_MS = 300000;          // CHANGED: 5 minutes (cards + advisory)
const SENSOR_REFRESH_MS = 300000;   // CHANGED: 5 minutes (live graph)
const MAX_SENSOR_POINTS = 60;

const LEVEL_COLORS = {
    healthy: '#4C9A5F',
    warning: '#E8B93B',
    critical: '#D9534F'
};

const el = id => document.getElementById(id);

// Safely set innerHTML (does nothing if the element is not on the page)
function setHtml(id, html) {
    const node = el(id);
    if (node) node.innerHTML = html;
}

/* NEW: turn Markdown such as **bold** into safe HTML.
   Uses marked + DOMPurify when they are loaded in dashboard.html.
   If they are missing, falls back to a simple built-in converter,
   so the "**" characters never show on the page. */
function renderMarkdown(text) {
    const source = text == null ? '' : String(text);

    if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
        const parse = typeof marked.parse === 'function' ? marked.parse : marked;
        return DOMPurify.sanitize(parse(source));
    }

    // Fallback: escape HTML first, then convert **bold**, *italic* and line breaks
    return source
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[^*])\*(?!\s)(.+?)\*(?!\*)/g, '$1<em>$2</em>')
        .replace(/\n/g, '<br>');
}

const loadingState = el('loading-state');
const errorState = el('error-state');
const dashboardContent = el('dashboard-content');

let forecastChart = null;
let stressChart = null;
let sensorReadingChart = null;
let fieldMap = null;
let firstLoad = true;

let sensorHistory = [];
let sensorRefreshTimer = null;
let sensorRequestInProgress = false;


/* ===== UI STATES ===== */

function showLoading() {
    loadingState.classList.remove('hidden');
    errorState.classList.add('hidden');
    dashboardContent.classList.add('hidden');
}

function showError(message) {
    if (loadingState) loadingState.classList.add('hidden');
    if (errorState) errorState.classList.remove('hidden');
    if (dashboardContent) dashboardContent.classList.add('hidden');

    const errorMessage = el('error-message');

    if (errorMessage) {
        errorMessage.textContent =
            message || 'Unable to load irrigation advisory.';
    }

    console.error('Advisory service error:', message);
}

function showContent() {
    loadingState.classList.add('hidden');
    errorState.classList.add('hidden');
    dashboardContent.classList.remove('hidden');
}


/* ===== DATA ===== */

async function fetchJson(url) {
    const res = await fetch(url, { cache: 'no-store' });

    if (!res.ok) {
        const body = await res.json().catch(() => ({}));

        throw new Error(
            body.message || `Request to ${url} failed (${res.status})`
        );
    }

    return res.json();
}

async function loadAll() {
    if (firstLoad) showLoading();

    try {
        const [analysis, daily, latest] = await Promise.all([
            fetchJson('/api/advisory'),
            fetchJson('/api/sensor-data/daily').catch(() => []),
            fetchJson('/api/sensor-data/latest').catch(() => null)
        ]);

        render(analysis, daily, latest);
        showContent();
        initFieldMap();

        firstLoad = false;
    } catch (err) {
        if (firstLoad) {
            showError(err.message);
        } else {
            console.error('Refresh failed:', err);
        }
    }
}


/* ===== RENDER ===== */

const capitalize = s =>
    s ? s.charAt(0).toUpperCase() + s.slice(1) : '—';

function render(a, daily, latest) {
    el('last-updated-time').textContent =
        new Date().toLocaleTimeString();

    /* --- Live sensor cards (newest saved reading) --- */

    const live = latest && latest.moisture != null
        ? latest.moisture
        : a.current_moisture;

    el('live-moisture-value').innerHTML =
        `${live ?? '—'}<span>%</span>`;

    // Temperature and humidity: newest reading, or today's daily average as a fallback
    const lastDay = daily && daily.length ? daily[daily.length - 1] : null;

    const temp = latest && latest.temperature != null
        ? latest.temperature
        : (lastDay ? lastDay.temperature : null);

    const hum = latest && latest.humidity != null
        ? latest.humidity
        : (lastDay ? lastDay.humidity : null);

    setHtml(
        'live-temp-value',
        temp != null && Number.isFinite(Number(temp))
            ? `${Number(temp).toFixed(1)}<span>°C</span>`
            : '—'
    );

    setHtml(
        'live-humidity-value',
        hum != null && Number.isFinite(Number(hum))
            ? `${Number(hum).toFixed(1)}<span>%</span>`
            : '—'
    );

    // How old is the newest reading? (makes an offline sensor obvious)
    const ageEl = el('live-age');

    if (ageEl) {
        if (latest && latest.readingTime) {
            const mins = Math.round(
                (Date.now() - getSensorTimestamp(latest).getTime()) / 60000
            );

            ageEl.textContent =
                mins < 2 ? 'just now'
                : mins < 60 ? `${mins} min ago`
                : mins < 1440 ? `${Math.round(mins / 60)} h ago`
                : `${Math.round(mins / 1440)} days ago`;

            ageEl.style.color = mins > 15 ? '#D9534F' : '#617065';
        } else {
            ageEl.textContent = '';
        }
    }

    /* --- AI result cards --- */

    const cond = el('soil-condition-value');

    const moistureForCondition = Number(live);
    let soilCondition;

    if (live == null || live === '' || !Number.isFinite(moistureForCondition)) {
        soilCondition = a.soil_condition || '';
    } else if (moistureForCondition < 15) {
        soilCondition = 'critical';
    } else if (moistureForCondition < 25) {
        soilCondition = 'dry';
    } else if (moistureForCondition <= 35) {
        soilCondition = 'normal';
    } else {
        soilCondition = 'wet';
    }

    cond.textContent = capitalize(soilCondition);
    cond.dataset.level = soilCondition;


    const health = Number(a.soil_health_score);
    el('health-value').innerHTML =
        `${Number.isFinite(health) ? health.toFixed(1) : '—'}<span>/100</span>`;


    renderWeather(a.weather_outlook);
    renderWindows(a.irrigation);
    renderGauge(a.irrigation);
    renderAlert(a.water_stress_alert);
    renderNextIrrigation(a);

    // CHANGED: render Markdown (**bold**) instead of showing raw asterisks
    el('advisory-text').innerHTML =
        renderMarkdown(a.advisory || 'No advisory available.');

    renderShapChips(a.shap_explanation);
    renderForecastChart(a, daily);
    renderStressChart(a);

    const notes = [...(a.warnings || [])];

    if (a.model_info && a.model_info.trained_on) {
        notes.push(
            `Forecast model: ${a.model_info.trained_on}. Advisory only.`
        );
    }

    el('forecast-note').textContent = notes.join(' ');

    // Feed the latest reading into the live chart too.
    // Duplicate records are filtered by the sensor-chart functions.
    if (latest) {
        addSensorReading(latest);
    }
}

function weatherIcon(rain) {
    if (rain >= 60) return '🌧️';
    if (rain >= 35) return '⛅';
    if (rain >= 15) return '🌤️';
    return '☀️';
}

function renderWeather(days) {
    const box = el('weather-days');

    if (!days || !days.length) {
        box.textContent = 'No forecast available.';
        return;
    }

    box.innerHTML = days.slice(0, 5).map(d => {
        const name = d.date
            ? new Date(d.date + 'T00:00:00').toLocaleDateString(
                'en-IN',
                { weekday: 'short' }
            )
            : '—';

        return `
            <div class="fd-day">
                ${name}
                <span class="ico">${weatherIcon(Number(d.rain_chance_percent) || 0)}</span>
                <strong>${Math.round(Number(d.temperature) || 0)}°C</strong>
                <small>${Math.round(Number(d.rain_chance_percent) || 0)}% rain</small>
            </div>
        `;
    }).join('');
}

function renderWindows(irr) {
    const ul = el('irrigation-windows');

    if (!irr || !irr.windows || irr.windows.length === 0) {
        ul.innerHTML =
            '<li class="fd-win-none">No irrigation needed today. See the next irrigation date below.</li>';
        return;
    }

    ul.innerHTML = irr.windows.map(w => `
        <li>
            <span class="fd-win-dot">!</span>
            <div>
                <strong>${w.label}${w.date_label ? ' · ' + w.date_label : ''}</strong>
                <span>${w.start}${w.end ? '–' + w.end : ''} · ${w.depth_mm.min}–${w.depth_mm.max} mm</span>
            </div>
        </li>
    `).join('');
}

function renderGauge(irr) {
    const next = irr && irr.windows && irr.windows[0];
    const mm = next ? Number(next.depth_mm.estimate) || 0 : 0;
    const frac = Math.min(Math.max(mm / GAUGE_MAX_MM, 0), 1);

    el('gauge-fill').style.strokeDashoffset =
        251.33 * (1 - frac);

    el('gauge-needle').setAttribute(
        'transform',
        `rotate(${-90 + 180 * frac} 100 100)`
    );

    el('gauge-value').textContent =
        next ? `${mm} mm` : 'No water needed';

    el('gauge-range').textContent = next
        ? `Range ${next.depth_mm.min}–${next.depth_mm.max} mm (next irrigation)`
        : '';
}

function renderAlert(al) {
    const box = el('stress-alert');

    if (al && al.active) {
        const severe = al.severity === 'severe';

        box.className =
            'fd-alert ' + (severe ? 'alert-severe' : 'alert-moderate');

        el('alert-title').textContent =
            severe ? '⚠ Water stress alert' : '⚠ Water stress watch';

        el('alert-text').textContent =
            [al.message, al.detail].filter(Boolean).join(' ');
    } else {
        box.className = 'fd-alert alert-ok';
        el('alert-title').textContent = '✔ No water stress expected';

        el('alert-text').textContent =
            (al && al.message) ||
            'Soil moisture is forecast to stay in a healthy range.';
    }
}

function renderShapChips(shap) {
    const labels = {
        moisture: 'Moisture',
        temperature: 'Temperature',
        humidity: 'Humidity'
    };

    el('shap-chips').innerHTML = Object.entries(shap || {})
        .filter(([, value]) => Number.isFinite(Number(value)))
        .sort((x, y) => Number(y[1]) - Number(x[1]))
        .map(([k, v]) =>
            `<span class="fd-chip">${labels[k] ?? k} ${Math.round(Number(v) * 100)}%</span>`
        )
        .join('');
}


/* ===== NEXT IRRIGATION DATE ===== */

function formatDateLabel(iso) {
    return new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', {
        weekday: 'short', day: 'numeric', month: 'short'
    });
}

function daysFromToday(iso) {
    const target = new Date(iso + 'T00:00:00');
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((target - today) / 86400000);
}

function whenText(n) {
    if (n < 0) return 'This date has already passed (sensor data is out of date)';
    if (n === 0) return 'Today';
    if (n === 1) return 'Tomorrow';
    return `In ${n} days`;
}

function renderNextIrrigation(a) {
    const dateEl = el('next-date');
    if (!dateEl) return;   // block not added to the HTML yet

    const when = el('next-when');
    const basis = el('next-basis');
    const nowBox = el('irrigate-now');

    // 1) Irrigation needed today
    const first = a.irrigation && a.irrigation.windows && a.irrigation.windows[0];
    if (a.irrigation_required_now && first) {
        const after = a.moisture_after_current_irrigation != null
            ? ` Moisture should rise to about ${a.moisture_after_current_irrigation}%.` : '';
        nowBox.textContent =
            `💧 Irrigate today: about ${first.depth_mm.estimate} mm (${first.depth_mm.min}–${first.depth_mm.max} mm).${after}`;
        nowBox.style.display = 'block';
    } else {
        nowBox.textContent = '';
        nowBox.style.display = 'none';
    }

    // 2) Next irrigation date
    if (a.next_irrigation_status === 'predicted' && a.next_irrigation_date) {
        const n = daysFromToday(a.next_irrigation_date);
        dateEl.textContent = formatDateLabel(a.next_irrigation_date);
        when.textContent = whenText(n);
        when.dataset.state = n < 0 ? 'stale' : 'ok';
    } else if (a.next_irrigation_status === 'unavailable') {
        dateEl.textContent = 'Not available';
        when.textContent = a.next_irrigation_message || '';
        when.dataset.state = 'stale';
    } else {
        dateEl.textContent = 'None in the next 7 days';
        when.textContent = a.next_irrigation_message || '';
        when.dataset.state = 'ok';
    }

    // 3) Where the date comes from (forecast or soil-category schedule)
    let text = '';
    const win = a.next_irrigation_days_window;
    if (a.next_irrigation_source === 'category_window' && win) {
        const f = a.forecast_days_until_irrigation;
        text = `Schedule rule: ${a.soil_condition} soil is re-irrigated every ${win[0]}–${win[1]} days. ` +
               (f != null ? `The moisture forecast alone gave day +${f}.`
                          : 'The moisture forecast alone showed no need within 7 days.');
    } else if (a.next_irrigation_source === 'forecast') {
        text = `Based on the moisture forecast reaching the ${a.next_irrigation_trigger_moisture}% trigger.`;
    }
    const ref = a.next_irrigation_reference_date;
    if (ref && -daysFromToday(ref) >= 2) {
        text += ` Counted from the last sensor reading on ${formatDateLabel(ref)}; check that the ESP32 is sending data.`;
    }
    basis.textContent = text;

    // 4) "Why this date?" panel
    el('next-reason').textContent = a.next_irrigation_reason || '';
    const ul = el('next-factors');
    ul.innerHTML = '';
    const xai = a.next_irrigation_xai || {};
    (xai.factors || []).forEach(f => {
        const li = document.createElement('li');
        li.textContent = f.detail;
        ul.appendChild(li);
    });
    el('next-note').textContent = (xai.confidence_notes || []).join(' ');
}


/* ===== SOIL MOISTURE FORECAST CHART ===== */

function renderForecastChart(a, daily) {
    const past = (daily || []).slice(-7);
    const fc = a.forecast || [];
    const nPast = past.length;

    const pad = n => Array(n).fill(null);

    const lastActual = nPast
        ? past[nPast - 1].moisture
        : a.current_moisture;

    const lead = nPast > 0
        ? [...pad(nPast - 1), lastActual]
        : [];

    const labels = [
        ...past.map(d => new Date(d.date + 'T00:00:00')
            .toLocaleDateString('en-GB', {
                weekday: 'short',
                day: 'numeric',
                month: 'short'
            })),
        ...fc.map(f => f.label)
    ];

    const total = labels.length;
    const thr = a.thresholds || {
        dry_below: 25,
        critical_below: 15
    };

    const datasets = [
        {
            label: 'Actual soil moisture',
            data: [...past.map(d => d.moisture), ...pad(fc.length)],
            borderColor: '#2563eb',
            backgroundColor: '#2563eb',
            borderWidth: 2.5,
            tension: 0.35,
            pointRadius: 3
        },
        {
            label: 'Predicted (no irrigation)',
            data: [...lead, ...fc.map(f => f.moisture)],
            borderColor: '#3D8B50',
            borderDash: [6, 4],
            borderWidth: 2.5,
            tension: 0.35,
            pointRadius: 3
        },
        {
            label: '_upper',
            data: [...pad(nPast), ...fc.map(f => f.upper ?? f.moisture)],
            borderWidth: 0,
            pointRadius: 0,
            fill: false
        },
        {
            label: '_lower',
            data: [...pad(nPast), ...fc.map(f => f.lower ?? f.moisture)],
            borderWidth: 0,
            pointRadius: 0,
            fill: '-1',
            backgroundColor: 'rgba(76,154,95,0.15)'
        },
        {
            label: `Dry below ${thr.dry_below}%`,
            data: Array(total).fill(thr.dry_below),
            borderColor: '#E8B93B',
            borderDash: [5, 5],
            borderWidth: 1.5,
            pointRadius: 0
        },
        {
            label: `Critical below ${thr.critical_below}%`,
            data: Array(total).fill(thr.critical_below),
            borderColor: '#D9534F',
            borderDash: [5, 5],
            borderWidth: 1.5,
            pointRadius: 0
        }
    ];

    if (a.irrigation && a.irrigation.needed && a.forecast_with_plan) {
        datasets.splice(2, 0, {
            label: 'Predicted (with irrigation plan)',
            data: [...lead, ...a.forecast_with_plan],
            borderColor: '#0891b2',
            borderDash: [2, 3],
            borderWidth: 2.5,
            tension: 0.35,
            pointRadius: 3
        });
    }

    if (forecastChart) forecastChart.destroy();

    forecastChart = new Chart(el('forecastChart'), {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        filter: item => !item.text.startsWith('_'),
                        boxWidth: 14
                    }
                }
            },
            scales: {
                y: {
                    min: 0,
                    suggestedMax: 45,
                    title: {
                        display: true,
                        text: 'Soil moisture (%)'
                    },
                    grid: { color: '#e6eee3' }
                },
                x: { grid: { display: false } }
            }
        }
    });
}


/* ===== UPCOMING WATER STRESS CHART ===== */

function renderStressChart(a) {
    const o = a.water_stress_outlook || [];

    if (stressChart) stressChart.destroy();

    const thresholds = a.thresholds || { dry_below: 25 };

    stressChart = new Chart(el('stressChart'), {
        type: 'bar',
        data: {
            labels: o.map(p => p.weekday || p.label),
            datasets: [
                {
                    label: 'Predicted soil moisture (%)',
                    data: o.map(p => p.moisture),
                    backgroundColor: o.map(
                        p => LEVEL_COLORS[p.level] || LEVEL_COLORS.healthy
                    ),
                    borderRadius: 6,
                    borderColor: o.map(p => p.date === a.next_irrigation_date ? '#1f3a2a' : 'rgba(0,0,0,0)'),
                    borderWidth: 2
                },
                {
                    type: 'line',
                    label: 'Dry threshold',
                    data: o.map(() => thresholds.dry_below),
                    borderColor: '#8a8a8a',
                    borderDash: [6, 4],
                    borderWidth: 1.5,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        afterLabel: ctx =>
                            ctx.datasetIndex === 0 && o[ctx.dataIndex]
                                ? `Level: ${o[ctx.dataIndex].level}`
                                : ''
                    }
                }
            },
            scales: {
                y: {
                    min: 0,
                    suggestedMax: 45,
                    grid: { color: '#e6eee3' }
                },
                x: { grid: { display: false } }
            }
        }
    });
}


/* ===== LIVE SENSOR READINGS CHART ===== */

function getSensorValue(data, keys) {
    for (const key of keys) {
        const value = data?.[key];

        if (
            value !== null &&
            value !== undefined &&
            value !== '' &&
            Number.isFinite(Number(value))
        ) {
            return Number(value);
        }
    }

    return null;
}

function getSensorTimestamp(data) {
    const raw =
        data.timestamp ??
        data.recordedAt ??
        data.recorded_at ??
        data.createdAt ??
        data.created_at ??
        data.readingTime ??
        data.reading_time ??
        null;

    if (raw === null || raw === undefined || raw === '') {
        return new Date();
    }

    // Handle numeric Unix timestamps in seconds or milliseconds.
    if (typeof raw === 'number' || /^\d+$/.test(String(raw))) {
        const n = Number(raw);
        return new Date(n < 100000000000 ? n * 1000 : n);
    }

    const parsed = new Date(raw);
    return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
}

function updateSensorMessage(message) {
    const messageElement = el('sensor-chart-message');

    if (messageElement) {
        messageElement.textContent = message;
    }
}

function initializeSensorChart() {
    const canvas = el('sensorReadingChart');

    if (!canvas || typeof Chart === 'undefined' || sensorReadingChart) {
        return;
    }

    sensorReadingChart = new Chart(canvas, {
        type: 'line',

        data: {
            labels: [],
            datasets: [
                {
                    label: 'Soil moisture (%)',
                    data: [],
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37, 99, 235, 0.10)',
                    borderWidth: 2.5,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    tension: 0.3,
                    spanGaps: true,
                    yAxisID: 'y'
                },
                {
                    label: 'Temperature (°C)',
                    data: [],
                    borderColor: '#e67e22',
                    backgroundColor: 'rgba(230, 126, 34, 0.10)',
                    borderWidth: 2.5,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    tension: 0.3,
                    spanGaps: true,
                    yAxisID: 'y1'
                },
                {
                    label: 'Humidity (%)',
                    data: [],
                    borderColor: '#16a085',
                    backgroundColor: 'rgba(22, 160, 133, 0.10)',
                    borderWidth: 2.5,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    tension: 0.3,
                    spanGaps: true,
                    yAxisID: 'y'
                }
            ]
        },

        options: {
            responsive: true,
            maintainAspectRatio: false,

            interaction: {
                mode: 'index',
                intersect: false
            },

            plugins: {
                legend: {
                    position: 'bottom'
                }
            },

            scales: {
                x: {
                    title: {
                        display: true,
                        text: 'Reading time'
                    },
                    grid: { display: false }
                },

                y: {
                    type: 'linear',
                    position: 'left',
                    min: 0,
                    suggestedMax: 100,
                    title: {
                        display: true,
                        text: 'Moisture / humidity (%)'
                    }
                },

                y1: {
                    type: 'linear',
                    position: 'right',
                    title: {
                        display: true,
                        text: 'Temperature (°C)'
                    },
                    grid: { drawOnChartArea: false }
                }
            }
        }
    });
}

function updateSensorChart() {
    if (!sensorReadingChart) return;

    sensorReadingChart.data.labels = sensorHistory.map(
        point => point.timestamp.toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        })
    );

    sensorReadingChart.data.datasets[0].data =
        sensorHistory.map(point => point.moisture);

    sensorReadingChart.data.datasets[1].data =
        sensorHistory.map(point => point.temperature);

    sensorReadingChart.data.datasets[2].data =
        sensorHistory.map(point => point.humidity);

    sensorReadingChart.update('none');
}

function addSensorReading(data) {
    if (!data || typeof data !== 'object') return;

    // Accept common field names returned by Java/Spring Boot.
    const moisture = getSensorValue(data, [
        'moisture',
        'soilMoisture',
        'soil_moisture'
    ]);

    const temperature = getSensorValue(data, [
        'temperature',
        'temperatureC',
        'temperature_c',
        'temp',
        'tempC'
    ]);

    const humidity = getSensorValue(data, [
        'humidity',
        'relativeHumidity',
        'relative_humidity'
    ]);

    if (
        moisture === null &&
        temperature === null &&
        humidity === null
    ) {
        updateSensorMessage(
            'The sensor endpoint returned no recognized moisture, temperature or humidity fields.'
        );
        return;
    }

    const timestamp = getSensorTimestamp(data);

    // CHANGED: readingTime added so duplicates are detected for your API
    const id = data.id ??
        data.readingTime ??
        data.reading_time ??
        data.timestamp ??
        data.recordedAt ??
        data.recorded_at ??
        data.createdAt ??
        data.created_at ??
        null;

    // If the backend supplies a stable record ID or timestamp,
    // do not plot the same stored record repeatedly.
    if (id !== null) {
        const duplicate = sensorHistory.some(
            point => point.recordId !== null &&
                String(point.recordId) === String(id)
        );

        if (duplicate) {
            // CHANGED: message says 5 minutes
            updateSensorMessage(
                'No new saved sensor record yet. Checking again in 5 minutes.'
            );
            return;
        }
    }

    sensorHistory.push({
        timestamp,
        recordId: id,
        moisture,
        temperature,
        humidity
    });

    if (sensorHistory.length > MAX_SENSOR_POINTS) {
        sensorHistory.shift();
    }

    initializeSensorChart();
    updateSensorChart();

    const updated = el('sensor-chart-updated');

    if (updated) {
        updated.textContent = timestamp.toLocaleTimeString();
    }

    // CHANGED: message says 5 minutes
    updateSensorMessage(
        `Displaying ${sensorHistory.length} reading(s). The chart checks for updates every 5 minutes.`
    );
}

async function refreshSensorReadings() {
    if (sensorRequestInProgress) return;

    sensorRequestInProgress = true;

    try {
        const latest = await fetchJson('/api/sensor-data/latest');

        if (latest && typeof latest === 'object') {
            // Support either one record or a single-element response array.
            const reading = Array.isArray(latest)
                ? latest[0]
                : latest;

            if (reading) {
                addSensorReading(reading);
            } else {
                updateSensorMessage('No sensor readings are available yet.');
            }
        } else {
            updateSensorMessage('No sensor readings are available yet.');
        }
    } catch (error) {
        console.error('Sensor chart refresh failed:', error);

        // CHANGED: message says 5 minutes
        updateSensorMessage(
            'Unable to fetch sensor data. The graph will retry in 5 minutes.'
        );
    } finally {
        sensorRequestInProgress = false;
    }
}

// NEW: load the last saved readings so the graph is not empty on page load
async function loadSensorHistory() {
    try {
        const rows = await fetchJson('/api/sensor-data/recent');

        sensorHistory = [];

        if (Array.isArray(rows)) {
            rows.forEach(r => addSensorReading(r));
        }
    } catch (error) {
        console.error('Sensor history load failed:', error);
    }
}

// CHANGED: now loads history first, then starts the 5-minute polling
async function startSensorRefresh() {
    initializeSensorChart();

    // Clear any previous timer before starting another one.
    if (sensorRefreshTimer !== null) {
        clearInterval(sensorRefreshTimer);
    }

    // Draw saved readings first, then check for the newest one.
    await loadSensorHistory();
    refreshSensorReadings();

    // Then check the endpoint every 5 minutes.
    sensorRefreshTimer = setInterval(
        refreshSensorReadings,
        SENSOR_REFRESH_MS
    );
}


/* ===== FIELD MAP ===== */

function initFieldMap() {
    if (typeof L === 'undefined') return;

    if (!fieldMap) {
        fieldMap = L.map('field-map', {
            zoomControl: false,
            scrollWheelZoom: false
        }).setView([FIELD_LAT, FIELD_LON], 16);

        L.tileLayer(
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            {
                maxZoom: 19,
                attribution: 'Tiles © Esri'
            }
        ).addTo(fieldMap);

        L.circleMarker([FIELD_LAT, FIELD_LON], {
            radius: 9,
            color: '#fff',
            weight: 3,
            fillColor: '#2563eb',
            fillOpacity: 1
        }).addTo(fieldMap);

        el('field-caption').textContent =
            `Monitored field · ${FIELD_LAT.toFixed(4)}, ${FIELD_LON.toFixed(4)}`;
    }

    setTimeout(() => fieldMap.invalidateSize(), 150);
}


/* ===== START ===== */

el('retry-btn').addEventListener('click', () => {
    firstLoad = true;
    loadAll();
});

loadAll();
setInterval(loadAll, REFRESH_MS);

// Independent 5-minute polling for the live sensor graph.
startSensorRefresh();