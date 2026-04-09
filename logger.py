import logging
import json
import sys
from datetime import datetime

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "time": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage()
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

def setup_logger():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers if setup_logger is called multiple times
    if logger.handlers:
        return logger

    # Console Handler (Human readable)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s', '%H:%M:%S')
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # JSON File Handler for general logs
    try:
        file_handler = logging.FileHandler('bot.log')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(JsonFormatter())
        logger.addHandler(file_handler)
        
        # Specific file for clean window summaries
        window_handler = logging.FileHandler('windows.log')
        window_handler.setLevel(logging.INFO)
        window_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', '%Y-%m-%d %H:%M:%S'))
        logger.addHandler(window_handler)
        
        # Specific file for errors
        error_handler = logging.FileHandler('errors.log')
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(JsonFormatter())
        logger.addHandler(error_handler)
    except Exception as e:
        print(f"Could not setup file loggers: {e}")

    return logger

setup_logger()
