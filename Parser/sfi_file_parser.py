from Parser.shared_function_info import SharedFunctionInfo, CodeLine
from parse import parse
import re
import string

all_functions = {}
repeat_last_line = False


def set_repeat_line_flag(flag):
    global repeat_last_line
    repeat_last_line = flag


def get_next_line(file):
    with open(file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield line
            if repeat_last_line:
                set_repeat_line_flag(False)
                yield line
    yield None


def parse_array(lines, func_name):
    if "Start " not in (line := next(lines)):
        raise Exception(f"Error got line \"{line}\" not Start Array")
    const_list = parse_const_array(lines, func_name)
    array_literal = "[" + ", ".join(const_list) + "]"
    while "End " not in (line := next(lines)):
        pass
    if (line := next(lines)) != ">":
        set_repeat_line_flag(True)
    return array_literal


def parse_object(lines, func_name):
    if "Start " not in (line := next(lines)):
        raise Exception(f"Error got line \"{line}\" not Start Object")
    const_list = iter(parse_const_array(lines, func_name)[1:])
    object_literal = "{" + ", ".join([f"{key}: {value}" for key, value in zip(const_list, const_list)]) + "}"
    while "End " not in (line := next(lines)):
        pass
    return object_literal


def parse_bytecode_line(line):
    match = re.search(r"^[^@]+@ +(\d+) : ((?:[0-9a-fA-F]{2} )+) *(.+)$", line)
    if match:
        offset, opcode, inst = match.groups()
        return CodeLine(opcode=opcode, line=int(offset), inst=inst)
    raise ValueError(f"Invalid bytecode line format: {line}")


def parse_bytecode(line, lines):
    code_list = []
    while " @ " in line:
        code_list.append(parse_bytecode_line(line))
        line = next(lines)
    set_repeat_line_flag(True)
    return code_list


def parse_string(data: str, length: int) -> str:
    n = len(data)

    def is_hex(s):
        return all(c in string.hexdigits for c in s)

    def dfs(i, out, out_length):
        if out_length == length:
            if i == n:
                return out
            return None
        if i >= n:
            return None

        if i + 2 <= n and data[i] == '\\' and data[i + 1] == 'x': # \xXX / \xXXX / \xXXXX
            j = i + 2

            for l in (2, 3, 4):
                if j + l <= n:
                    hex_part = data[j:j + l]
                    if not is_hex(hex_part):
                        continue

                    code = int(hex_part, 16)

                    if code <= 0x06 or 0x0E <= code <= 0x1F or code == 0x7F:
                        res = dfs(j + l, out + r'\x' + hex_part, out_length + 1)
                        if res is not None:
                            return res
                        continue
                    elif code == 0x07:
                        res = dfs(j + l, out + r'\a', out_length + 1)
                        if res is not None:
                            return res
                        continue
                    elif code == 0x08:
                        res = dfs(j + l, out + r'\b', out_length + 1)
                        if res is not None:
                            return res
                        continue
                    elif code == 0x09:
                        res = dfs(j + l, out + r'\t', out_length + 1)
                        if res is not None:
                            return res
                        continue
                    elif code == 0x0A:
                        res = dfs(j + l, out + r'\n', out_length + 1)
                        if res is not None:
                            return res
                        continue
                    elif code == 0x0B:
                        res = dfs(j + l, out + r'\v', out_length + 1)
                        if res is not None:
                            return res
                        continue
                    elif code == 0x0C:
                        res = dfs(j + l, out + r'\f', out_length + 1)
                        if res is not None:
                            return res
                        continue
                    elif code == 0x0D:
                        res = dfs(j + l, out + r'\r', out_length + 1)
                        if res is not None:
                            return res
                        continue
                    elif 0xD800 <= code <= 0xDBFF:
                        k = j + l
                        if not (k + 6 <= n and data[k] == '\\' and data[k + 1] == 'x'):
                            res = dfs(j + l, out + r'\u' + hex_part, out_length + 1)
                            if res is not None:
                                return res
                            continue

                        low_hex = data[k + 2:k + 6]
                        if not is_hex(low_hex):
                            continue

                        low = int(low_hex, 16)
                        if not (0xDC00 <= low <= 0xDFFF):
                            continue

                        full_code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                        ch = chr(full_code)

                        res = dfs(k + 6, out + ch, out_length + 2)
                        if res is not None:
                            return res
                    elif 0xDC00 <= code <= 0xDFFF:
                        res = dfs(j + l, out + r'\u' + hex_part, out_length + 1)
                        if res is not None:
                            return res
                    else:
                        ch = chr(code)
                        res = dfs(j + l, out + ch, out_length + 1)
                        if res is not None:
                            return res

            return None
        elif i + 2 <= n and data[i] == '\\' and data[i + 1] == '\\': # \\
            return dfs(i + 2, out + '\\\\', out_length + 1)
        else: # normal char
            skipped = 1
            while i + skipped < n and data[i + skipped] != '\\': # reduce unnecessary recursive calls
                skipped += 1
            return dfs(i + skipped, out + data[i:i+skipped], out_length + skipped)

    result = dfs(0, "", 0)
    if result is None:
        raise ValueError("Invalid：found unknown unicode encoding rule")
    return result


def parse_const_line(lines, func_name):
    var_line = next(lines)
    match = re.search(r"^(\d+(?:\-\d+)?):\s(0x[0-9a-fA-F]+\s)?(.+)", var_line)
    if not match:
        raise ValueError(f"Invalid constant line format: {var_line}")

    idx_range, address, value = match.groups()
    var_idx = int(idx_range.split('-')[-1]) + 1

    if not address:
        return var_idx, value
    if value.startswith("<String"):
        [length, value] = parse("<String[{}]: {}>", value)
        [encoding, value] = value.split("#", 1)
        if encoding == "u":
            value = parse_string(value, int(length))
        value = value.replace('"', '\\"')
        return var_idx, f'"{value}"'
    if value.startswith("<SharedFunctionInfo"):
        value = value.split(" ", 1)[-1].rstrip('> ') if " " in value else ""
        return var_idx, parse_shared_function_info(lines, value, func_name)
    if value.startswith("<ArrayBoilerplateDescription") or value.startswith("<FixedArray"):
        return var_idx, parse_array(lines, func_name)
    if value.startswith("<ObjectBoilerplateDescription"):
        return var_idx, parse_object(lines, func_name)
    if value.startswith("<Odd Oddball"):
        return var_idx, "null"
    return var_idx, value.rstrip('>').split(" ", 1)[-1]


def parse_const_array(lines, func_name):
    while "- length:" not in (line := next(lines)):
        pass
    size = int(parse("- length:{}", line)[0])
    if not size:
        return []

    while not (line := next(lines)).startswith("0"):
        pass
    set_repeat_line_flag(True)

    value = ""
    next_idx = 0
    const_list = []

    for idx in range(size):
        if next_idx != idx:
            const_list.append(value)
            continue
        next_idx, value = parse_const_line(lines, func_name)
        const_list.append(value)

    return const_list


def parse_const_pool(line, lines, func_name):
    if "size = 0" in line:
        return []
    return parse_const_array(lines, func_name)


def parse_exception_table_line(line):
    from_, to_, key, _ = parse("({},{})  -> {} ({}", line)
    return int(key), [int(from_), int(to_)]


def parse_handler_table(line, lines):
    if "size = 0" in line:
        return {}
    exception_table = {}
    next(lines)
    while " -> " in (line := next(lines)):
        key, value = parse_exception_table_line(line)
        exception_table[key] = value
    set_repeat_line_flag(True)
    return exception_table


def parse_parameter_count(line):
    return int(parse("Parameter count {}", line)[0])


def parse_register_count(line):
    return int(parse("Register count {}", line)[0])


def parse_address(line):
    return parse("{}: [{}] in {}", line)[0]


def parse_shared_function_info(lines, name, declarer=None):
    sfi = SharedFunctionInfo()
    sfi.declarer = declarer
    sfi.name = 'func_unknown'
    address = ""
    while (line := next(lines)) not in ("End SharedFunctionInfo", None):
        if "Parameter count" in line:
            sfi.argument_count = parse_parameter_count(line)
        elif "Register count" in line:
            sfi.register_count = parse_register_count(line)
        elif "Constant pool" in line:
            sfi.const_pool = parse_const_pool(line, lines, sfi.name)
        elif "Handler Table" in line:
            sfi.exception_table = parse_handler_table(line, lines)
        elif "@    0 : " in line:
            sfi.code = parse_bytecode(line, lines)
        elif "[SharedFunctionInfo]" in line or "[BytecodeArray]" in line:
            address = parse_address(line)
            sfi.name = f'func_{(name or "unknown")}_{address}'

    all_functions[sfi.name] = sfi

    if not sfi.is_fully_parsed():
        raise ValueError(f"Incomplete parsing of function: {sfi.name}")

    return sfi.name


def parse_file(file="test.txt"):
    lines = get_next_line(file)
    while next(lines) != "Start SharedFunctionInfo":
        pass

    parse_shared_function_info(lines, "start")
    return all_functions


if __name__ == '__main__':
    parse_file()
