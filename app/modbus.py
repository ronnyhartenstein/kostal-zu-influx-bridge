import logging
import socket
from typing import List, Optional

from pymodbus.client import ModbusTcpClient

logger = logging.getLogger("kostal_bridge.modbus")


class ModbusConnection:
    def __init__(self, hosts: List[str], port: int, unit_id: int, timeout: float) -> None:
        self.hosts = hosts
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self._client: Optional[ModbusTcpClient] = None
        self.active_host: Optional[str] = None

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.connected

    def ensure(self) -> bool:
        """Connect or reconnect if needed. Returns True if a new connection was made."""
        if self._client is None:
            self._connect()
            return True
        if not self._client.connected:
            logger.warning("Modbus connection dropped. Reconnecting.")
            self.reset()
            self._connect()
            return True
        return False

    def reset(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self.active_host = None

    def read_holding(self, address: int, count: int) -> List[int]:
        assert self._client is not None
        response = self._client.read_holding_registers(
            address=address, count=count, slave=self.unit_id
        )
        if response.isError():
            raise RuntimeError(f"Modbus read failed at {address} count={count}: {response}")
        return list(response.registers)

    def _connect(self) -> None:
        for host in self.hosts:
            if not host:
                continue
            try:
                socket.gethostbyname(host)
            except socket.gaierror:
                logger.warning("Host not resolvable: %s", host)
                continue

            client = ModbusTcpClient(host=host, port=self.port, timeout=self.timeout)
            if client.connect():
                self._client = client
                self.active_host = host
                logger.info("Connected to Modbus host %s:%s", host, self.port)
                return

            logger.warning("Could not connect to Modbus host %s:%s", host, self.port)
            client.close()

        raise ConnectionError("Unable to connect to any configured Modbus host")
