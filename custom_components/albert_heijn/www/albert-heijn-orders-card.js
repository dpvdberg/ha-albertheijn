class AlbertHeijnOrdersCard extends HTMLElement {
  static get properties() {
    return { hass: {}, config: {} };
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  setConfig(config) {
    this._config = config;
    this._entityId = config.entity || "sensor.albert_heijn_open_orders";
  }

  getCardSize() {
    return 3;
  }

  static getConfigElement() {
    return document.createElement("albert-heijn-orders-card-editor");
  }

  static getStubConfig() {
    return { entity: "sensor.albert_heijn_open_orders" };
  }

  _render() {
    if (!this._hass || !this._entityId) return;

    const entity = this._hass.states[this._entityId];
    if (!entity) {
      this.innerHTML = `<ha-card header="Albert Heijn"><div class="card-content">Entity not found: ${this._entityId}</div></ha-card>`;
      return;
    }

    const orders = entity.attributes.orders || [];
    const now = new Date();

    // Sort by delivery date
    const sorted = [...orders].sort((a, b) => a.delivery_date.localeCompare(b.delivery_date));

    // Find the first non-finalized order's deadline
    let firstDeadline = null;
    for (const order of sorted) {
      if (order.modifiable && order.items === 0 && order.closing_time) {
        firstDeadline = order.closing_time;
        break;
      }
    }

    this.innerHTML = `
      <ha-card>
        <div class="card-header">
          <div class="name">
            <span class="ah-icon">🛒</span> Albert Heijn Orders
          </div>
          ${firstDeadline ? `<div class="deadline">⏰ ${this._formatDeadline(firstDeadline, now)}</div>` : ""}
        </div>
        <div class="card-content">
          ${sorted.length === 0 ? '<div class="empty">Geen bestellingen</div>' : ""}
          ${sorted.map(order => this._renderOrder(order, now)).join("")}
        </div>
      </ha-card>
      <style>
        :host {
          --ah-blue: #00a0e2;
          --ah-green: #4caf50;
          --ah-orange: #ff9800;
          --ah-red: #f44336;
          --ah-gray: #9e9e9e;
        }
        .card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 16px 16px 0;
        }
        .card-header .name {
          font-size: 1.1em;
          font-weight: 500;
        }
        .ah-icon {
          font-size: 1.2em;
        }
        .deadline {
          font-size: 0.8em;
          color: var(--ah-orange);
          font-weight: 500;
        }
        .card-content {
          padding: 12px 16px 16px;
        }
        .order-row {
          display: flex;
          align-items: center;
          padding: 10px 0;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
        }
        .order-row:last-child {
          border-bottom: none;
        }
        .badge {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          margin-right: 12px;
          flex-shrink: 0;
        }
        .badge.empty { background: var(--ah-red); }
        .badge.partial { background: var(--ah-orange); }
        .badge.ready { background: var(--ah-green); }
        .badge.delivered { background: var(--ah-blue); }
        .badge.closed { background: var(--ah-gray); }
        .order-info {
          flex: 1;
          min-width: 0;
        }
        .order-date {
          font-weight: 500;
          font-size: 0.95em;
        }
        .order-time {
          font-size: 0.8em;
          color: var(--secondary-text-color);
        }
        .order-meta {
          text-align: right;
          flex-shrink: 0;
        }
        .order-total {
          font-weight: 500;
          font-size: 0.95em;
        }
        .order-items {
          font-size: 0.75em;
          color: var(--secondary-text-color);
        }
        .order-state {
          font-size: 0.7em;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-top: 2px;
        }
        .state-needs-items { color: var(--ah-red); }
        .state-below-min { color: var(--ah-orange); }
        .state-ready { color: var(--ah-green); }
        .state-delivering { color: var(--ah-blue); }
        .state-closed { color: var(--ah-gray); }
        .empty {
          text-align: center;
          color: var(--secondary-text-color);
          padding: 16px;
        }
      </style>
    `;
  }

  _renderOrder(order, now) {
    const badge = this._getBadge(order);
    const stateInfo = this._getStateInfo(order);
    const total = order.total > 0 ? `€${order.total.toFixed(2)}` : "—";
    const items = order.items !== null ? `${order.items} items` : "";

    return `
      <div class="order-row">
        <div class="badge ${badge}"></div>
        <div class="order-info">
          <div class="order-date">${this._capitalize(order.delivery_date_display || order.delivery_date)}</div>
          <div class="order-time">${order.time}</div>
        </div>
        <div class="order-meta">
          <div class="order-total">${total}</div>
          <div class="order-items">${items}</div>
          <div class="order-state ${stateInfo.class}">${stateInfo.label}</div>
        </div>
      </div>
    `;
  }

  _getBadge(order) {
    if (order.state === "OUT_FOR_DELIVERY" || order.state === "DELIVERED") return "delivered";
    if (!order.modifiable) return "closed";
    if (order.items === 0) return "empty";
    if (order.total < 50) return "partial";
    return "ready";
  }

  _getStateInfo(order) {
    if (order.state === "OUT_FOR_DELIVERY") return { label: "Onderweg", class: "state-delivering" };
    if (order.state === "DELIVERED") return { label: "Bezorgd", class: "state-delivering" };
    if (!order.modifiable) return { label: "Gesloten", class: "state-closed" };
    if (order.items === 0) return { label: "Leeg", class: "state-needs-items" };
    if (order.total < 50) return { label: "Onder minimum", class: "state-below-min" };
    return { label: "Klaar", class: "state-ready" };
  }

  _formatDeadline(isoStr, now) {
    const deadline = new Date(isoStr);
    const diff = deadline - now;
    if (diff < 0) return "Verlopen";
    const days = Math.floor(diff / 86400000);
    const hours = Math.floor((diff % 86400000) / 3600000);
    if (days > 1) return `Deadline: ${days}d ${hours}u`;
    if (days === 1) return `Deadline: morgen ${deadline.getHours()}:${String(deadline.getMinutes()).padStart(2, "0")}`;
    return `Deadline: ${hours}u ${Math.floor((diff % 3600000) / 60000)}min`;
  }

  _capitalize(str) {
    if (!str) return "";
    return str.charAt(0).toUpperCase() + str.slice(1);
  }
}

customElements.define("albert-heijn-orders-card", AlbertHeijnOrdersCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "albert-heijn-orders-card",
  name: "Albert Heijn Orders",
  description: "Shows upcoming Albert Heijn orders with status badges and deadlines.",
});
