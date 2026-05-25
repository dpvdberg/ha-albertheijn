# Albert Heijn Integration for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)

A Home Assistant custom integration for Albert Heijn grocery delivery, providing order tracking sensors and voice control through Assist.

## Features

### Sensors
- **Next delivery date** — when your next order arrives
- **Next delivery time** — delivery time window (e.g., "18:00 - 20:00")
- **Next order total** — total price of the upcoming order
- **Next order status** — current status description
- **Next order edit deadline** — the last moment you can modify your order (timestamp sensor, great for automations!)
- **Next order modifiable** — whether the order can still be changed
- **Next order items** — number of products in the order
- **Minimum order value** — subscription minimum (with `remaining_to_minimum` attribute)
- **Order submittable** — whether the order meets the minimum value
- **Open orders** — total number of pending deliveries

### Services
- `albert_heijn.search_products` — search for products
- `albert_heijn.add_to_order` — add a product by ID
- `albert_heijn.add_product_by_name` — search and add the first match
- `albert_heijn.reopen_order` — reopen a submitted order for editing
- `albert_heijn.revert_order` — revert a reopened order

### Voice Control (Assist)
Works with Home Assistant's built-in Assist in both Dutch and English:

**Dutch:**
- "Voeg melk toe aan mijn bestelling"
- "Bestel 2 brood"
- "Wanneer wordt mijn bestelling bezorgd?"

**English:**
- "Add milk to my order"
- "Order 2 bread"
- "When will my groceries be delivered?"

## Installation

### HACS (Recommended)
1. Add this repository as a custom repository in HACS
2. Search for "Albert Heijn" and install
3. Restart Home Assistant

### Manual
1. Copy the `custom_components/albert_heijn` folder to your HA `custom_components/` directory
2. Restart Home Assistant

## Configuration

### Setup in Home Assistant
1. Go to **Settings → Devices & Services → Add Integration**
2. Search for "Albert Heijn"
3. Enter your Albert Heijn email and password
4. The integration will log in, obtain tokens, and set up sensors

Tokens are automatically stored, refreshed, and re-created using your stored credentials if they expire.

### Requirements

The integration uses [`curl_cffi`](https://github.com/yifeikong/curl_cffi) to impersonate a Chrome browser during login (helps bypass TLS fingerprinting and reduces captcha triggers). This is installed automatically as a dependency.

If the automated login is blocked by hCaptcha, you can alternatively obtain tokens via the [appie CLI tool](appie-go/) and store them manually.

## Automation Examples

### Notify before order deadline
```yaml
automation:
  - alias: "AH Order Deadline Reminder"
    trigger:
      - platform: template
        value_template: >
          {{ (as_timestamp(states('sensor.albert_heijn_next_order_edit_deadline')) - as_timestamp(now())) < 7200 }}
    condition:
      - condition: state
        entity_id: sensor.albert_heijn_next_order_modifiable
        state: "Yes"
    action:
      - service: notify.mobile_app
        data:
          title: "Albert Heijn bestelling"
          message: >
            Je bestelling sluit over 2 uur! 
            Totaal: €{{ states('sensor.albert_heijn_next_order_total') }}
            ({{ state_attr('sensor.albert_heijn_minimum_order_value', 'remaining_to_minimum') | round(2) }}€ onder minimum)
```

### Notify when minimum not reached
```yaml
automation:
  - alias: "AH Minimum Order Warning"
    trigger:
      - platform: state
        entity_id: sensor.albert_heijn_order_submittable
        to: "No"
    action:
      - service: notify.mobile_app
        data:
          title: "Albert Heijn"
          message: >
            Je bestelling is onder het minimum van €{{ states('sensor.albert_heijn_minimum_order_value') }}.
            Nog €{{ state_attr('sensor.albert_heijn_minimum_order_value', 'remaining_to_minimum') | round(2) }} nodig.
```

## API Reference

This integration is built from the Albert Heijn mobile API, documented in `appie-go/doc/albertheijn_api.md`. The Go reference implementation in `appie-go/` shows the full API capabilities.

## License

MIT
