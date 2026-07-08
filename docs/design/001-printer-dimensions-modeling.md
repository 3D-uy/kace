# ADR 001: Separation of Machine Geometry and Printable Area

## Status
Proposed

## Context
In the current implementation of KACE, the reported printable build volume is derived directly from the motor travel limits (`position_max`). This model assumes that the printable area of the bed matches the absolute physical movement bounds of the toolhead.

However, on many modern Klipper-based printers, the toolhead is designed to travel outside the printable bed boundaries for maintenance, calibration, or tool-changing operations:
* **Off-bed parking**: Negative homing offsets (e.g. endstop located at `X = -15` off-bed).
* **Purge zones & nozzle brushes**: Safe travel extends beyond the printable bed to reach accessories.
* **Docking stations**: Toolheads or probes (such as Dockable Clicky/Euclid probes) are parked outside the print area.
* **Shifted/Asymmetric origins**: The center of the physical bed might not align with the absolute mechanical origin `(0,0)`.

Binding these two concepts results in incorrect build volume sizes reported to slicers and Web UIs (Mainsail/Fluidd), which in turn could lead to nozzle collisions or extrusion in mid-air.

## Decision
We will decouple the printer dimension model into two related but independent data models: **Machine Geometry** (physical movement limits) and **Printable Area** (logical bed boundaries).

### 1. Machine Geometry (Physical)
Represents the actual boundaries where the stepper motors are allowed to move.

```yaml
machine_geometry:
  x:
    position_min: -15
    position_max: 320
    position_endstop: -15
  y:
    position_min: -10
    position_max: 310
    position_endstop: -10
  z:
    position_min: -0.5
    position_max: 355
    position_endstop: 0
```

### 2. Printable Area (Logical)
Represents the boundaries where material can be deposited. Using coordinate ranges (`x_min`/`x_max`, `y_min`/`y_max`) instead of simple widths/heights supports shifted origins and asymmetric beds.

```yaml
printable_area:
  x_min: 0
  x_max: 300
  y_min: 0
  y_max: 300
  z_max: 350
```

---

## Validation Layer
To ensure safety and physical consistency, KACE will run a validation pass on the combined models. The configuration is rejected if any of the following constraints are violated:

* **Width Constraint**: 
  $$\text{printable\_area.x\_max} - \text{printable\_area.x\_min} \le \text{machine\_geometry.x.position\_max} - \text{machine\_geometry.x.position\_min}$$
* **Depth Constraint**: 
  $$\text{printable\_area.y\_max} - \text{printable\_area.y\_min} \le \text{machine\_geometry.y.position\_max} - \text{machine\_geometry.y.position\_min}$$
* **Height Constraint**: 
  $$\text{printable\_area.z\_max} \le \text{machine\_geometry.z.position\_max} - \text{machine\_geometry.z.position\_min}$$
* **Bounds Inclusion**:
  $$\text{printable\_area.x\_min} \ge \text{machine\_geometry.x.position\_min} \quad \text{and} \quad \text{printable\_area.x\_max} \le \text{machine\_geometry.x.position\_max}$$
  $$\text{printable\_area.y\_min} \ge \text{machine\_geometry.y.position\_min} \quad \text{and} \quad \text{printable\_area.y\_max} \le \text{machine\_geometry.y.position\_max}$$
* **Endstop Bounding**: For each axis, the `position_endstop` must be bounded within the mechanical travel limits:
  $$\text{position\_endstop} \in [\text{position\_min}, \text{position\_max}]$$

---

## UI Presentation (Wizard Flow)
The KACE configuration wizard will expose these concepts in two separate, sequential steps to ensure clarity:

### Step 1 — Machine Geometry
User configures the physical kinematic limits:
* Mechanical endpoints (`position_min`, `position_max`).
* Endstop trigger position (`position_endstop`).
* Homing direction.

### Step 2 — Printable Area
User defines the logical bed dimensions relative to the mechanical travel space:
* Printable limits: `X Min / X Max`, `Y Min / Y Max`.
* Max print height: `Z Max`.

**Visualization**: The wizard UI will render a 2D/3D overlay showing the logical **Printable Area** centered or positioned inside the bounding box of the **Machine Geometry**. This visual representation will highlight off-bed travel zones (margins) and immediately warn users if the print area exceeds physical limits.

---

## Consequences & Long-Term Benefits
* **Automated Bed Mesh Calibration**: Safe limits for `mesh_min` and `mesh_max` can be calculated automatically by combining the printable bed bounds with the probe's X/Y offsets.
* **Safe Homing**: Automatic calculation of `safe_z_home` coordinates (usually centered on the printable bed).
* **Better Compatibility**: Support for advanced layouts such as IDEX (Independent Dual Extruders), tool changers, nozzle-cleaning brushes, and wipe/purge zones.
* **Accurate Slicing**: Slicer profiles can read the true bed size boundaries, preventing prints from executing off-bed.
