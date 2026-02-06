# Stopfinder Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant integration for [Stopfinder](https://www.transfinder.com/stopfinder/) by Transfinder. This integration allows you to track school bus schedules, pickup/drop-off times, and bus information for your students.

## Features

- **Next Pickup Time**: Shows the next scheduled bus pickup time
- **Next Drop-off Time**: Shows the next scheduled drop-off time
- **Bus Number**: Displays the assigned bus number
- **School Information**: Shows the student's school and grade

Each student registered in your Stopfinder account gets their own set of sensors in Home Assistant.

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add `https://github.com/VoltageSolutions/ha-stopfinder` as a custom repository with category "Integration"
6. Click "Add"
7. Search for "Stopfinder" and install it
8. Restart Home Assistant

### Manual Installation

1. Download the latest release from the GitHub repository
2. Copy the `custom_components/stopfinder` folder to your Home Assistant's `custom_components` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "Stopfinder"
4. Enter your credentials:
   - **Transfinder Base URL**: Your school district's Transfinder URL (e.g., `https://www.mytransfinder.com`)
   - **Email**: Your Stopfinder account email
   - **Password**: Your Stopfinder account password

## Sensors

For each student, the following sensors are created:

| Sensor | Description | Attributes |
|--------|-------------|------------|
| Next Pickup | Next scheduled pickup time | stop_name, bus_number, trip_name |
| Next Drop-off | Next scheduled drop-off time | stop_name, bus_number, trip_name |
| Bus Number | Current bus assignment | - |
| School | Student's school | grade |

## Example Automations

### Notify When Bus is Coming Soon

```yaml
automation:
  - alias: "Bus Arriving Soon"
    trigger:
      - platform: template
        value_template: >
          {{ (as_timestamp(states('sensor.john_doe_next_pickup')) - as_timestamp(now())) < 600 }}
    action:
      - service: notify.mobile_app
        data:
          title: "Bus Alert"
          message: >
            Bus {{ state_attr('sensor.john_doe_next_pickup', 'bus_number') }}
            arriving in less than 10 minutes at {{ state_attr('sensor.john_doe_next_pickup', 'stop_name') }}
```

### Dashboard Card Example

```yaml
type: entities
title: School Bus Schedule
entities:
  - entity: sensor.john_doe_next_pickup
    name: Pickup Time
  - entity: sensor.john_doe_next_dropoff
    name: Drop-off Time
  - entity: sensor.john_doe_bus_number
    name: Bus
  - entity: sensor.john_doe_school
    name: School
```

## Troubleshooting

### Cannot Connect

- Verify your Transfinder base URL is correct for your school district
- Ensure you can log in to the Stopfinder mobile app with your credentials
- Check that your school district uses Stopfinder

### No Data

- The integration fetches schedules for the next 7 days
- If no trips are scheduled, sensors may show as unavailable
- School holidays or breaks may result in no scheduled trips

## Credits

This integration is based on the API implementation from [Stopfinder-Integrator](https://github.com/VoltageSolutions/Stopfinder-Integrator) by Voltage Solutions.

## License

This project is licensed under the MIT License.
