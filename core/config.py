import os
from typing import Any, Callable, List, Optional, TypeVar, Union

# Generic Type
T = TypeVar("T")


class Settings:
    """
    DeltaX settings configuration.
    """

    def __init__(self):
        self.api_id: int = self._get_env_var("API_ID", int)
        self.api_hash: str = self._get_env_var("API_HASH", str)
        self.bot_token: str = self._get_env_var("BOT_TOKEN", str)
        self.channel_log: Optional[int] = self._get_env_var(
            "CHANNEL_LOG", int, optional=True
        )
        self.download_path: str = self._get_env_var(
            "DOWNLOAD_PATH", str, default="downloads"
        )
        self.database_uri: str = self._get_env_var("DATABASE_URI", str, optional=True)
        self.devs_id: List[int] = self._parse_id_list(
            self._get_env_var("DEVS_ID", str, default="5466401085")
        )
        self.owner_id: List[int] = self._parse_id_list(
            self._get_env_var("OWNER_ID", str)
        )

        self.session_string: str = self._get_env_var(
            "SESSIONS_STRING", str, optional=True
        )

    def _get_env_var(
        self,
        var_name: str,
        var_type: Callable[[Any], T],
        optional: bool = False,
        default: Any = None,
    ) -> Optional[T]:
        """
        Get and convert environment variable.

        Args:
            var_name: Name of the environment variable
            var_type: Expected data type
            optional: Whether the variable is optional
            default: Default value if variable is not found

        Returns:
            Converted value of the specified type or default value

        Raises:
            ValueError: If the environment variable is not found and not optional
        """
        value = os.getenv(var_name, default)
        if value is None and not optional:
            raise ValueError(f"Environment variable '{var_name}' not found.")
        if value is None:
            return None
        try:
            return var_type(value)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Environment variable '{var_name}' must be of type {var_type.__name__}: {str(e)}"
            )

    def _parse_id_list(self, value: Union[int, str, List[int]]) -> List[int]:
        """
        Validate and parse owner_id and devs_id fields, ensuring they are lists of integers.

        Args:
            value: Input value to validate

        Returns:
            List of integer IDs

        Raises:
            ValueError: If input cannot be converted to a list of integers
        """
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            value = value.strip()
            if value.isdigit():
                return [int(value)]
            # Convert comma-separated string to list of integers
            id_list = []
            for item in value.split(","):
                item = item.strip()
                if item.isdigit():
                    id_list.append(int(item))
                else:
                    raise ValueError(f"Invalid integer value in list: '{item}'")
            return id_list
        if isinstance(value, list):
            if all(isinstance(item, int) for item in value):
                return value
            raise ValueError("All items in the list must be integers.")
        raise ValueError(
            "owner_id and devs_id must be an int, comma-separated string, or list of integers."
        )


from dotenv import load_dotenv

env_file = "config.env" if os.path.exists("config.env") else ".env"
load_dotenv(env_file)

# Initialize configuration
config = Settings()
