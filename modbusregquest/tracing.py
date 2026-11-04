# SPDX-License-Identifier: Apache-2.0
"""Transport-independent dissection of captured ADUs, including partial frames."""
import json
import struct

FUNCTION_NAMES = {1: "Read coils", 2: "Read discrete inputs", 3: "Read holding registers",
    4: "Read input registers", 5: "Write single coil", 6: "Write single register",
    15: "Write multiple coils", 16: "Write multiple registers", 22: "Mask write register"}
EXCEPTIONS = {1: "Illegal function", 2: "Illegal data address", 3: "Illegal data value",
    4: "Server device failure", 5: "Acknowledge", 6: "Server device busy",
    8: "Memory parity error", 10: "Gateway path unavailable", 11: "Gateway target failed to respond"}


def hex_dump(data):
    return "\n".join(f"{offset:04X}  " + " ".join(f"{value:02X}" for value in data[offset:offset+16])
                     for offset in range(0, len(data), 16))


def dissect_pdu(pdu, *, response=False, request=b""):
    if not pdu:
        return {}
    function = pdu[0]
    result = {"function": f"0x{function:02X}", "operation": FUNCTION_NAMES.get(function & 0x7F, "Unknown")}
    if function & 0x80:
        if len(pdu) >= 2:
            result.update(exception_code=f"0x{pdu[1]:02X}", exception=EXCEPTIONS.get(pdu[1], "Unknown exception"))
        return result
    if response and function in (1, 2, 3, 4):
        if len(pdu) < 2:
            return result
        result["byte_count"] = pdu[1]
        data = pdu[2:]
        if len(data) != pdu[1]:
            result["incomplete"] = True
        if function in (3, 4):
            result["registers"] = [int.from_bytes(data[i:i+2], "big") for i in range(0, len(data)-1, 2)]
        else:
            count = int.from_bytes(request[3:5], "big") if len(request) >= 5 else len(data)*8
            result["bits"] = [(data[i//8] >> (i % 8)) & 1 for i in range(min(count, len(data)*8))]
        return result
    if len(pdu) < 5:
        result["incomplete"] = True
        return result
    result["address"] = int.from_bytes(pdu[1:3], "big")
    field = int.from_bytes(pdu[3:5], "big")
    if function in (1, 2, 3, 4, 15, 16):
        result["count"] = field
        if not response and function in (15, 16) and len(pdu) >= 6:
            result["byte_count"] = pdu[5]
            data = pdu[6:]
            if len(data) != pdu[5]:
                result["incomplete"] = True
            result["values"] = ([(data[i//8] >> (i % 8)) & 1 for i in range(min(field, len(data)*8))]
                if function == 15 else [int.from_bytes(data[i:i+2], "big") for i in range(0, len(data)-1, 2)])
    elif function in (5, 6):
        result["value"] = field == 0xFF00 if function == 5 else field
        result["raw_value"] = f"0x{field:04X}"
    elif function == 22:
        result["and_mask"] = f"0x{field:04X}"
        if len(pdu) >= 7:
            result["or_mask"] = f"0x{int.from_bytes(pdu[5:7], 'big'):04X}"
        else:
            result["incomplete"] = True
    return result


def dissect_frame(data, transport, *, response=False, request_pdu=b""):
    if not data:
        return {}
    result = {"transport": transport.upper(), "frame_bytes": len(data)}
    if transport == "rtu":
        from .protocol import crc16
        result["unit_id"] = data[0]
        if len(data) < 4:
            result["incomplete"] = True
            return result
        result["crc"] = f"0x{int.from_bytes(data[-2:], 'little'):04X}"
        result["crc_valid"] = crc16(data[:-2]) == int.from_bytes(data[-2:], "little")
        pdu = data[1:-2]
    else:
        if len(data) < 7:
            result["incomplete"] = True
            return result
        transaction, protocol, length, unit = struct.unpack(">HHHB", data[:7])
        result.update(transaction_id=transaction, protocol_id=protocol, length=length, unit_id=unit)
        if len(data) != length + 6:
            result["incomplete"] = True
        pdu = data[7:]
    result.update(dissect_pdu(pdu, response=response, request=request_pdu))
    return result


def export_event(event):
    result = {key: (value.hex(" ").upper() if isinstance(value, bytes) else value) for key, value in event.items()}
    result["decoded_request"] = dissect_frame(event.get("request", b""), event.get("transport", "tcp"))
    result["decoded_response"] = dissect_frame(event.get("response", b""), event.get("transport", "tcp"),
                                               response=True, request_pdu=event.get("request_pdu", b""))
    return result


def decoded_text(event, response=False):
    key = "response" if response else "request"
    frame = event.get(key, b"")
    result = dissect_frame(frame, event.get("transport", "tcp"), response=response,
                           request_pdu=event.get("request_pdu", b""))
    if response and event.get("decoded_values"):
        result["parameter_values"] = event["decoded_values"]
    if not response:
        result["bytes_sent"] = event.get("sent", 0)
    if event.get("error"):
        result["error"] = event["error"]
    if event.get("transport") == "demo":
        result["simulated"] = True
    return json.dumps(result, ensure_ascii=False, indent=2)


def frame_groups(event, response=False):
    """Return labeled spans of *captured* bytes; register addresses are PDU addresses."""
    frame = event.get("response" if response else "request", b"")
    if not response:
        frame = frame[:event.get("sent", 0)]
    transport = event.get("transport", "tcp")
    groups = []
    def add(start, size, label, *, address=None, kind="header"):
        data = frame[start:min(start+size, len(frame))]
        if data:
            groups.append({"label": label, "data": data, "offset": start, "address": address,
                           "kind": kind, "partial": len(data) < size})
    if transport == "rtu":
        add(0, 1, "unit_id")
        base, end = 1, len(frame)
        expected = None
        if len(frame) >= 2:
            fc = frame[1]
            if response:
                expected = 5 if fc & 0x80 else (5+frame[2] if fc in (1, 2, 3, 4) and len(frame) > 2 else 10 if fc == 22 else 8 if fc in (5, 6, 15, 16) else None)
            else:
                expected = len(event.get("request", b""))
        crc_start = len(frame)-2 if expected == len(frame) else None
        if crc_start is not None:
            end = crc_start
    else:
        for start, size, name in ((0,2,"transaction_id"),(2,2,"protocol_id"),(4,2,"length"),(6,1,"unit_id")):
            add(start, size, name)
        base, end, crc_start = 7, len(frame), None
    if end <= base:
        return groups
    pdu = frame[base:end]
    fc = pdu[0]
    add(base, 1, "function")
    if fc & 0x80:
        add(base+1, 1, "exception_code")
    elif response and fc in (1,2,3,4):
        add(base+1, 1, "data_length")
        request = event.get("request_pdu", b"")
        address = int.from_bytes(request[1:3], "big") if len(request) >= 3 else None
        if fc in (3,4):
            for offset in range(base+2, end, 2):
                index = (offset-base-2)//2
                add(offset, min(2,end-offset), "register", address=None if address is None else address+index, kind="data")
        else:
            for offset in range(base+2, end):
                add(offset, 1, "data", address=None if address is None else address+(offset-base-2)*8, kind="data")
    else:
        add(base+1, 2, "address")
        address = int.from_bytes(pdu[1:3], "big") if len(pdu) >= 3 else None
        if fc in (1,2,3,4,15,16):
            add(base+3, 2, "count")
            if not response and fc in (15,16):
                add(base+5, 1, "data_length")
                width = 2 if fc == 16 else 1
                for offset in range(base+6, end, width):
                    index = (offset-base-6)//width
                    add(offset, min(width,end-offset), "register" if fc == 16 else "data",
                        address=None if address is None else address+index*(1 if fc == 16 else 8), kind="data")
        elif fc in (5,6):
            add(base+3, 2, "register" if fc == 6 else "data", address=address, kind="data")
        elif fc == 22:
            add(base+3, 2, "and_mask", address=address, kind="data")
            add(base+5, 2, "or_mask", address=address, kind="data")
        else:
            for offset in range(base+1, end, 4):
                add(offset, min(4,end-offset), "data", kind="data")
    if crc_start is not None:
        add(crc_start, 2, "crc", kind="crc")
    return groups
