"""Python API for Neware Battery Testing System.

Contains a single class NewareAPI that provides methods to interact with the
Neware Battery Testing System.
"""

import socket
from types import TracebackType

from defusedxml import ElementTree


def _auto_convert_type(value: str) -> int | float | str | None:
    """Try to automatically convert a string to float or int."""
    if value == "--":
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _xml_to_records(
    xml_string: str,
    list_name: str = "list",
) -> list[dict]:
    """Extract elements inside <list> tags, convert to a list of dictionaries.

    Args:
        xml_string: raw xml string
        list_name: the tag that contains the list of elements to parse

    Returns:
        list of dictionaries like 'orient = records' in JSON

    """
    # Parse response XML string
    root = ElementTree.fromstring(xml_string)
    # Find <list> element
    list_element = root.find(list_name)
    # Extract <name> elements to a list of dictionaries
    result = []
    for el in list_element:
        el_dict = el.attrib
        if el.text:
            el_dict[el.tag] = el.text
        result.append(el_dict)
    return [{k: _auto_convert_type(v) for k, v in el.items()} for el in result]


def _xml_to_lists(
    xml_string: str,
    list_name: str = "list",
) -> dict[str, list]:
    """Extract elements inside <list> tags, convert to a dictionary of lists.

    Args:
        xml_string: raw xml string
        list_name: the tag that contains the list of elements to parse

    Returns:
        dict where keys are the names of records, each has a list of values
            like 'orient = list' in JSON

    """
    result = _xml_to_records(xml_string, list_name)
    return _lod_to_dol(result)


def _lod_to_dol(ld: list[dict]) -> dict[str, list]:
    """Convert list of dictionaries to dictionary of lists."""
    return {k: [d[k] for d in ld] for k in ld[0]}


class NewareAPI:
    """Python API for Neware Battery Testing System.

    Provides a method to send and receive commands to the Neware Battery Testing
    System with xml strings, and convenience methods to start, stop, and get the
    status and data from the channels.
    """

    def __init__(self, ip: str = "127.0.0.1", port: int = 502) -> None:
        """Initialize the NewareAPI object with the IP, port, and channel map."""
        self.ip = ip
        self.port = port
        self.neware_socket = socket.socket()
        self.channel_map: dict[str, dict] = {}
        self.start_message = '<?xml version="1.0" encoding="UTF-8" ?><bts version="1.0">'
        self.end_message = "</bts>"
        self.termination = "\n\n#\r\n"

    def connect(self) -> None:
        """Establish the TCP connection."""
        self.neware_socket.connect((self.ip, self.port))
        connect = "<cmd>connect</cmd><username>admin</username><password>neware</password><type>bfgs</type>"
        self.command(connect)
        self.update_channel_map()

    def disconnect(self) -> None:
        """Close the port."""
        if self.neware_socket:
            self.neware_socket.close()

    def __enter__(self) -> "NewareAPI":
        """Establish the TCP connection when entering the context."""
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the port when exiting the context."""
        self.disconnect()

    def __del__(self) -> None:
        """Close the port when the object is deleted."""
        self.disconnect()

    def command(self, cmd: str) -> str:
        """Send a command to the device, and return the response."""
        self.neware_socket.sendall(
            str.encode(self.start_message + cmd + self.end_message + self.termination, "utf-8"),
        )
        received = ""
        while not received.endswith(self.termination):
            received += self.neware_socket.recv(2048).decode()
        return received[: -len(self.termination)]

    def start_job(
        self,
        pipeline: str,
        sampleid: str,
        payload_xml_path: str,
        save_location: str = "C:\\Neware data\\",
    ) -> str:
        """Start designated payload file on a pipeline.

        Args:
            pipeline: pipeline to start the job on
            sampleid: barcode used in Newares BTS software
            payload_xml_path: path to payload file
            save_location: location to save the data

        Returns:
            str: XML string response

        """
        pip = self.channel_map[pipeline]
        cmd = (
            "<cmd>start</cmd>"
            '<list count="1" DBC_CAN="1">'
            f'<start ip="{pip["ip"]}" devtype="{pip["devtype"]}" devid="{pip["devid"]}" '
            f'subdevid="{pip["subdevid"]}" '
            f'chlid="{pip["Channelid"]}" '
            f'barcode="{sampleid}">'
            f"{payload_xml_path}</start>"
            f'<backup backupdir="{save_location}" remotedir="" filenametype="0" '
            'customfilename="" addtimewhenrepeat="0" createdirbydate="0" '
            'filetype="0" backupontime="0" backupontimeinterval="720" '
            'backupfree="1" />'
            "</list>"
        )
        return self.command(cmd)

    def stop_job(self, pipelines: str | list[str] | tuple[str]) -> str:
        """Stop job running on pipeline(s)."""
        if isinstance(pipelines, str):
            pipelines = [pipelines]

        header = f'<cmd>stop</cmd><list count = "{len(pipelines)}">'
        cmd_string = ""
        for pipeline in pipelines:
            pip = self.channel_map[pipeline]
            cmd_string += (
                f'\t\t<stop ip="{pip["ip"]}" devtype="{pip["devtype"]}" devid="{pip["devid"]}" '
                f'subdevid="{pip["subdevid"]}" chlid="{pip["Channelid"]}">true</stop>\n'
            )
        footer = "</list>"
        return self.command(header + cmd_string + footer)

    def get_status(self, pipeline_ids: str | list[str] | None = None) -> dict[str, dict]:
        """Get status of pipeline(s).

        Args:
            pipeline_ids (optional): pipeline ID or list of pipeline IDs
                if not given, all pipelines from channel map are used

        Returns:
            a dictionary per channel with status

        Raises:
            KeyError: if pipeline ID not in the channel map

        """
        # Get the (subset) of the channel map
        if not pipeline_ids:  # If no argument passed use all pipelines
            pipelines = self.channel_map
        if isinstance(pipeline_ids, str):
            pipelines = {pipeline_ids: self.channel_map[pipeline_ids]}
        elif isinstance(pipeline_ids, list):
            pipelines = {p: self.channel_map[p] for p in pipeline_ids}

        # Create and submit command XML string
        header = f'<cmd>getchlstatus</cmd><list count = "{len(pipelines)}">'
        middle = ""
        for pip in pipelines.values():
            middle += (
                f'<status ip="{pip["ip"]}" devtype="{pip["devtype"]}" '
                f'devid="{pip["devid"]}" subdevid="{pip["subdevid"]}" chlid="{pip["Channelid"]}">true</status>'
            )
        footer = "</list>"
        xml_string = self.command(header + middle + footer)
        records = _xml_to_records(xml_string)

        # It seems like in the Neware response the subdevid is ALWAYS 1, this looks like a bug on their end
        # E.g. if you request the status of 13-5-5 it correctly gets the status of 13-5-5, but tells you it is returning
        # the status of 13-1-5.
        # Workaround: instead of returning the result directly, we merge it with the input pipelines, prioritising the
        # (correct) channel information from the channel map.
        return {
            pipeline_id: {**record, **pipeline_dict}
            for (pipeline_id, pipeline_dict), record in zip(pipelines.items(), records, strict=True)
        }

    def inquire_channel(self, pipeline_ids: str | list[str] | None = None) -> dict[str, dict]:
        """Inquire the status of the channel.

        Returns useful information like device id, cycle number, step, workstatus, current, voltage,
        time, and whether the channel is currently open.

        Args:
            pipeline_ids (optional): pipeline IDs or list of pipeline Ids
                default: None, will get all pipeline IDs in the channel map

        Returns:
            a dictionary per channel with the latest info and data point
                key is the pipeline ID e.g. "13-1-5"

        """
        # Get the (subset) of the channel map
        if not pipeline_ids:  # If no argument passed use all pipelines
            pipelines = self.channel_map
        if isinstance(pipeline_ids, str):
            pipelines = {pipeline_ids: self.channel_map[pipeline_ids]}
        elif isinstance(pipeline_ids, list):
            pipelines = {p: self.channel_map[p] for p in pipeline_ids}

        # Create and submit command XML string
        header = f'<cmd>inquire</cmd><list count = "{len(pipelines)}">'
        middle = ""
        for pip in pipelines.values():
            middle += (
                f'<inquire ip="{pip["ip"]}" devtype="{pip["devtype"]}" '
                f'devid="{pip["devid"]}" subdevid="{pip["subdevid"]}" chlid="{pip["Channelid"]}"\n'
                'aux="0" barcode="1">true</inquire>'
            )
        footer = "</list>"
        xml_string = self.command(header + middle + footer)

        records = _xml_to_records(xml_string)

        return {
            pipeline_id: {**record, **pipeline_dict}
            for (pipeline_id, pipeline_dict), record in zip(pipelines.items(), records, strict=True)
        }

    def download_data(self, pipeline: str) -> dict[str, list]:
        """Download the data points for chlid.

        Uses the channel map to get the device id, subdevice id, and channel id.

        """
        chunk_size = 1000
        data: list[dict] = []
        pip = self.channel_map[pipeline]
        while len(data) % chunk_size == 0:
            cmd_string = (
                "<cmd>download</cmd>"
                f'<download devtype="{pip["devtype"]}" devid="{pip["devid"]}" '
                f'subdevid="{pip["subdevid"]}" chlid="{pip["Channelid"]}" '
                f'auxid="0" testid="0" startpos="{len(data) + 1}" count="{chunk_size}"/>'
            )
            xml_string = self.command(cmd_string)
            data += _xml_to_records(xml_string)
        # Orient as dict of lists
        return _lod_to_dol(data)

    def device_info(self) -> list[dict]:
        """Get device information.

        Returns:
            IP, device type, device id, sub-device id and channel id of all channels

        """
        command = "<cmd>getdevinfo</cmd>"
        xml_string = self.command(command)
        return _xml_to_records(xml_string, "middle")

    def update_channel_map(self) -> None:
        """Update the channel map with the latest device information."""
        devices = self.device_info()
        self.channel_map = {f"{d['devid']}-{d['subdevid']}-{d['Channelid']}": d for d in devices}
