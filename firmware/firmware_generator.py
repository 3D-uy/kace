import os

def generate_firmware_config(config_dict, klipper_path="~/klipper", *, processor=None, board=None):
    """
    Generates a .config file in the Klipper directory based on the configuration dict.
    """
    klipper_path = os.path.expanduser(klipper_path)
    config_file_path = os.path.join(klipper_path, ".config")

    try:
        from .startup_gpio import required_startup_pins
        if required_startup_pins(board) and processor is None:
            raise ValueError("Selected-board startup GPIO requires an explicit processor")
        if processor is not None:
            from .configuration import klipper_config
            config_dict = klipper_config(config_dict, processor, board=board)
        # Check if the path exists, though on some setups it might not be cloned yet
        if not os.path.exists(klipper_path):
            return False, f"Klipper directory not found at {klipper_path}"
            
        with open(config_file_path, "w", encoding="utf-8") as f:
            for key, value in config_dict.items():
                f.write(f"{key}={value}\n")
                
        return True, "Successfully created minimal .config"
    except Exception as e:
        return False, f"Failed to generate firmware config: {str(e)}"
