"""
Logging configuration for the application
"""
import logging
import sys
from datetime import datetime

def setup_logging():
    """Setup logging configuration - safe for uvicorn reloads"""
    try:
        # Create logs directory if it doesn't exist
        import os
        # Get the backend-python directory (parent of app directory)
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        
        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        simple_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        
        # Root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # Check if logging is already configured (to avoid conflicts during uvicorn reloads)
        # Only set up if we don't have our custom handlers already
        has_file_handler = any(
            isinstance(h, logging.FileHandler) and 'app_' in getattr(h.baseFilename, '', '')
            for h in root_logger.handlers
        )
        
        if not has_file_handler:
            # Clear existing handlers to avoid conflicts during uvicorn reloads
            existing_handlers = root_logger.handlers[:]
            for handler in existing_handlers:
                try:
                    handler.close()
                    root_logger.removeHandler(handler)
                except (AttributeError, RuntimeError, ValueError):
                    # Ignore errors when clearing handlers (common during reloads)
                    pass
            
            # Console handler
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(simple_formatter)
            
            # File handler for all logs
            try:
                file_handler = logging.FileHandler(
                    os.path.join(logs_dir, f'app_{datetime.now().strftime("%Y%m%d")}.log'),
                    encoding='utf-8'
                )
                file_handler.setLevel(logging.DEBUG)
                file_handler.setFormatter(detailed_formatter)
                
                # File handler for errors only
                error_handler = logging.FileHandler(
                    os.path.join(logs_dir, f'error_{datetime.now().strftime("%Y%m%d")}.log'),
                    encoding='utf-8'
                )
                error_handler.setLevel(logging.ERROR)
                error_handler.setFormatter(detailed_formatter)
                
                # Add handlers
                root_logger.addHandler(console_handler)
                root_logger.addHandler(file_handler)
                root_logger.addHandler(error_handler)
            except (OSError, PermissionError) as e:
                # If file handlers can't be created, at least add console handler
                root_logger.addHandler(console_handler)
                logging.warning(f"Could not create file handlers: {e}")
        
        return root_logger
    except Exception as e:
        # Fallback: just ensure basic logging works
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        logging.warning(f"Error in setup_logging, using basic config: {e}")
        return logging.getLogger()

def get_logger(name):
    """Get a logger instance"""
    return logging.getLogger(name)

