import { escapeHtml } from './utils.js';

export function renderTable(container, { columns, rows, emptyMessage = 'データがありません。' }) {
  if (!rows.length) {
    container.innerHTML = `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
    return;
  }

  const head = columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join('');
  const body = rows
    .map((row) => {
      const cells = columns
        .map((column) => {
          const value = typeof column.render === 'function' ? column.render(row) : row[column.key];
          return `<td>${value}</td>`;
        })
        .join('');
      return `<tr>${cells}</tr>`;
    })
    .join('');

  container.innerHTML = `
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}
