import os
import copy
from core.translations import t, get_mode
from core.exceptions import WizardExit

_BACK = "__back__"
_QUIT = "__quit__"

PHASE_MAP = {
    "board": "Hardware",
    "fan_assignment": "Hardware",
    "z_motors": "Hardware",
    "z_socket_assignment": "Hardware",
    "driver_type": "Hardware",
    "driver_mode": "Hardware",
    "printer_profile": "Motion",
    "profile_review": "Motion",
    "kinematics": "Motion",
    "x_volume": "Motion",
    "y_volume": "Motion",
    "z_volume": "Motion",
    "x_limits": "Motion",
    "y_limits": "Motion",
    "z_limits": "Motion",
    "probe": "Sensors",
    "bltouch_pins": "Sensors",
    "probe_offsets": "Sensors",
    "hotend_therm": "Sensors",
    "bed_therm": "Sensors",
    "display": "Software",
    "web_ui": "Software",
}

PHASE_KEYS = {
    "Hardware": "wizard.phase.hardware",
    "Motion": "wizard.phase.motion",
    "Sensors": "wizard.phase.sensors",
    "Software": "wizard.phase.software",
}

PHASE_ORDER = ["Hardware", "Motion", "Sensors", "Software"]


class WizardRunner:
    def __init__(self, steps_config, step_order, initial_data=None):
        self.steps_config = steps_config
        self.step_order = step_order
        self.history_stack = []
        self.snapshots = {}
        self.user_data = initial_data if initial_data is not None else {}
        self.last_step_id = None
        self.completed_phases = set()

    def run(self, start_step_id):
        # Local import to avoid circular dependency
        from core.wizard.ui import _print_step_header

        current_id = start_step_id
        
        while current_id:
            step_cfg = self.steps_config[current_id]
            
            # Take snapshot before executing the step
            self.snapshots[current_id] = copy.deepcopy(self.user_data)
            
            # Detect forward transitions between phases
            current_phase = PHASE_MAP.get(current_id)
            if self.last_step_id:
                last_phase = PHASE_MAP.get(self.last_step_id)
                if last_phase and current_phase and last_phase != current_phase:
                    if PHASE_ORDER.index(current_phase) > PHASE_ORDER.index(last_phase):
                        if last_phase not in self.completed_phases:
                            self.completed_phases.add(last_phase)
                            if os.environ.get("KACE_AUTO") != "1" and os.environ.get("KACE_QUIET") != "1":
                                if get_mode() == "Beginner":
                                    last_phase_key = PHASE_KEYS.get(last_phase)
                                    translated_last_phase = t(last_phase_key) if last_phase_key else last_phase
                                    print(f"\033[92m{t('wizard.phase.complete', phase=translated_last_phase)}\033[0m")
            
            # Print the header orientation box for the step
            _print_step_header(current_id, self.user_data)
            
            try:
                ans = step_cfg["prompt"](self.user_data)
            except (KeyboardInterrupt, EOFError):
                raise WizardExit()
                
            if ans == _BACK:
                if self.history_stack:
                    prev_id = self.history_stack[-1]
                    self.rollback_to(prev_id)
                    current_id = prev_id
                continue
                
            if ans == "__retry__":
                self.rollback_to(current_id)
                continue
                
            if current_id not in self.history_stack:
                self.history_stack.append(current_id)
            self.last_step_id = current_id
                
            next_func = step_cfg.get("next")
            if next_func:
                next_id = next_func(ans, self.user_data)
            else:
                next_id = self.get_default_next(current_id)
                
            current_id = next_id
            
        return self.user_data

    def rollback_to(self, step_id):
        """Rolls back user_data state to the snapshot taken before step_id was run,
        and removes step_id and all subsequent steps from history and snapshots."""
        snapshot = self.snapshots.get(step_id)
        if snapshot is not None:
            self.user_data.clear()
            self.user_data.update(copy.deepcopy(snapshot))
            
        if step_id in self.history_stack:
            idx = self.history_stack.index(step_id)
            self.history_stack = self.history_stack[:idx]
            
        # Clean up all snapshots that are not in the active history stack path.
        # This prevents orphaned snapshots from branch changes or back navigation.
        active_steps = set(self.history_stack)
        for sid in list(self.snapshots.keys()):
            if sid not in active_steps:
                self.snapshots.pop(sid, None)
                
        self.last_step_id = self.history_stack[-1] if self.history_stack else None
        target_phase = PHASE_MAP.get(step_id)
        if target_phase in PHASE_ORDER:
            target_idx = PHASE_ORDER.index(target_phase)
            self.completed_phases = {p for p in self.completed_phases if PHASE_ORDER.index(p) < target_idx}

    def get_default_next(self, step_id):
        try:
            idx = self.step_order.index(step_id)
            if idx + 1 < len(self.step_order):
                return self.step_order[idx + 1]
        except ValueError:
            pass
        return None
