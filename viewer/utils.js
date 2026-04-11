export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

export function parseCsv(text) {
  const rows = [];
  let current = '';
  let row = [];
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];

    if (char === '"') {
      if (inQuotes && next === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (char === ',' && !inQuotes) {
      row.push(current);
      current = '';
      continue;
    }
    if ((char === '\n' || char === '\r') && !inQuotes) {
      if (char === '\r' && next === '\n') {
        i += 1;
      }
      row.push(current);
      if (row.length > 1 || row[0] !== '') {
        rows.push(row);
      }
      row = [];
      current = '';
      continue;
    }
    current += char;
  }

  if (current !== '' || row.length) {
    row.push(current);
    rows.push(row);
  }
  if (!rows.length) {
    return [];
  }

  const [header, ...body] = rows;
  return body.map((cells) => {
    const record = {};
    header.forEach((column, index) => {
      record[column] = cells[index] ?? '';
    });
    return record;
  });
}

export function safeParseJson(text) {
  return JSON.parse(text);
}

export function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || value === '') {
    return 'N/A';
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value);
  }
  return numeric.toLocaleString('ja-JP', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

export function formatPercent(value, digits = 2) {
  if (value === null || value === undefined || value === '') {
    return 'N/A';
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value);
  }
  return `${(numeric * 100).toFixed(digits)}%`;
}

export function formatBytes(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return 'N/A';
  }
  if (numeric < 1024) {
    return `${numeric} B`;
  }
  const units = ['KB', 'MB', 'GB'];
  let size = numeric / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unitIndex]}`;
}

export function formatDate(value) {
  if (!value) {
    return 'N/A';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat('ja-JP', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
}

export function summarizeNumericSeries(rows, key) {
  const values = rows
    .map((row) => Number(row[key]))
    .filter((value) => Number.isFinite(value));
  if (!values.length) {
    return null;
  }
  return {
    min: Math.min(...values),
    max: Math.max(...values),
    last: values.at(-1),
  };
}

export function summarizePriceData(rows) {
  if (!rows.length) {
    return [];
  }
  const numericColumns = ['Open', 'High', 'Low', 'Close', 'Volume'];
  return numericColumns
    .map((column) => {
      const summary = summarizeNumericSeries(rows, column);
      if (!summary) {
        return null;
      }
      return {
        label: column,
        value: `${formatNumber(summary.min)} - ${formatNumber(summary.max)}`,
        subValue: `最新 ${formatNumber(summary.last)}`,
      };
    })
    .filter(Boolean);
}

export function toMarkdownHtml(markdown) {
  const lines = String(markdown ?? '').split(/\r?\n/);
  const chunks = [];
  let inList = false;
  let inCode = false;

  function closeList() {
    if (inList) {
      chunks.push('</ul>');
      inList = false;
    }
  }

  lines.forEach((line) => {
    if (line.startsWith('```')) {
      closeList();
      chunks.push(inCode ? '</pre>' : '<pre>');
      inCode = !inCode;
      return;
    }
    if (inCode) {
      chunks.push(`${escapeHtml(line)}\n`);
      return;
    }
    if (!line.trim()) {
      closeList();
      return;
    }
    if (line.startsWith('# ')) {
      closeList();
      chunks.push(`<h1>${escapeHtml(line.slice(2))}</h1>`);
      return;
    }
    if (line.startsWith('## ')) {
      closeList();
      chunks.push(`<h2>${escapeHtml(line.slice(3))}</h2>`);
      return;
    }
    if (line.startsWith('### ')) {
      closeList();
      chunks.push(`<h3>${escapeHtml(line.slice(4))}</h3>`);
      return;
    }
    if (line.startsWith('- ')) {
      if (!inList) {
        chunks.push('<ul>');
        inList = true;
      }
      chunks.push(`<li>${escapeHtml(line.slice(2))}</li>`);
      return;
    }
    closeList();
    chunks.push(`<p>${escapeHtml(line)}</p>`);
  });

  closeList();
  if (inCode) {
    chunks.push('</pre>');
  }
  return chunks.join('');
}
