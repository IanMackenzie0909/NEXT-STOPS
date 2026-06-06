import math
import os
import requests
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parent


def load_root_env():
    env_path = ROOT.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_first(*names, default=""):
    load_root_env()
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


client_id = env_first('TDX_MRT_CLIENT_ID', 'TDX_CLIENT_ID', default='your_TDX_MRT_client_id')
client_secret = env_first('TDX_MRT_CLIENT_SECRET', 'TDX_CLIENT_SECRET', default='your_TDX_MRT_client_secret')

BASE_URL = 'https://tdx.transportdata.tw/api/basic/v2'
OPERATOR = 'TRTC'

SERVICE_STATUS = {
    0: '正常',
    1: '尚未發車',
    2: '交管不停靠',
    3: '末班車已過',
    4: '今日未營運',
}


class TDXRateLimitError(Exception):
    pass


class TDX():
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret

    def get_token(self):
        token_url = 'https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token'
        headers = {'content-type': 'application/x-www-form-urlencoded'}
        data = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        response = requests.post(token_url, headers=headers, data=data, timeout=10)
        response.raise_for_status()
        return response.json()['access_token']

    def get_response(self, url, retries=2):
        headers = {'authorization': f'Bearer {self.get_token()}'}

        for attempt in range(retries + 1):
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 429:
                retry_after = parse_int(response.headers.get('Retry-After'), 5)
                if attempt < retries:
                    time.sleep(retry_after)
                    continue
                raise TDXRateLimitError(
                    f'TDX API request limit reached. Please wait and try again. URL: {url}'
                )

            response.raise_for_status()
            return response.json()

        return []


def get_name_zh(name):
    if isinstance(name, dict):
        return name.get('Zh_tw', '') or name.get('En', '')
    return name or ''


def get_station_name_zh(station_name):
    return get_name_zh(station_name)


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_service_status(item):
    status_code = parse_int(item.get('ServiceStatus'))
    return SERVICE_STATUS.get(status_code, f'未知狀態({status_code})')


def format_update_time(time_text):
    if not time_text:
        return ''

    try:
        return datetime.fromisoformat(time_text).strftime('%H:%M:%S')
    except ValueError:
        return time_text


def format_estimate_time(item):
    status_code = parse_int(item.get('ServiceStatus'))
    if status_code != 0:
        return get_service_status(item)

    if item.get('EstimateTime') in (None, ''):
        return '無資料'

    estimate_seconds = parse_int(item.get('EstimateTime'))
    if estimate_seconds <= 0:
        return '進站中'
    if estimate_seconds < 60:
        return '1 分內'

    return f'{math.ceil(estimate_seconds / 60)} 分'


def get_mrt_status(item):
    status_code = parse_int(item.get('ServiceStatus'))
    if status_code != 0:
        return get_service_status(item)
    return format_estimate_time(item)


def get_direction_key(item):
    return (
        item.get('DestinationStationID')
        or item.get('DestinationStaionID')
        or item.get('TripHeadSign')
        or 'unknown'
    )


def get_direction_label(item):
    trip_head_sign = item.get('TripHeadSign', '')
    destination = get_name_zh(item.get('DestinationStationName', ''))

    if trip_head_sign:
        return trip_head_sign
    if destination:
        return f'往{destination}'
    return '未知方向'


def get_liveboard_url(station_id=None):
    url = f'{BASE_URL}/Rail/Metro/LiveBoard/{OPERATOR}/'
    query = ['$format=JSON']

    if station_id:
        filter_text = quote(f"StationID eq '{station_id}'", safe="'")
        query.insert(0, f'$filter={filter_text}')

    return f'{url}?{"&".join(query)}'


def text_width(text):
    width = 0
    for char in str(text):
        if unicodedata.east_asian_width(char) in ('F', 'W'):
            width += 2
        else:
            width += 1
    return width


def pad_text(text, width):
    text = str(text)
    return text + ' ' * (width - text_width(text))


def print_table(headers, rows):
    column_widths = [
        max(text_width(header), *(text_width(row[index]) for row in rows))
        for index, header in enumerate(headers)
    ]

    top = '┌' + '┬'.join('─' * (width + 2) for width in column_widths) + '┐'
    divider = '├' + '┼'.join('─' * (width + 2) for width in column_widths) + '┤'
    bottom = '└' + '┴'.join('─' * (width + 2) for width in column_widths) + '┘'

    def format_row(values):
        cells = [
            f" {pad_text(value, column_widths[index])} "
            for index, value in enumerate(values)
        ]
        return '│' + '│'.join(cells) + '│'

    print(top)
    print(format_row(headers))
    print(divider)
    for row in rows:
        print(format_row(row))
    print(bottom)


def sort_liveboard_item(item):
    status_code = parse_int(item.get('ServiceStatus'))
    estimate_seconds = parse_int(item.get('EstimateTime'), 999999)
    return (
        item.get('LineID', ''),
        get_direction_key(item),
        status_code != 0,
        estimate_seconds,
        get_name_zh(item.get('DestinationStationName', '')),
    )


def group_liveboards_by_direction(liveboards):
    groups = []
    by_key = {}

    for item in sorted(liveboards, key=sort_liveboard_item):
        key = get_direction_key(item)
        if key not in by_key:
            by_key[key] = {
                'label': get_direction_label(item),
                'destination': get_name_zh(item.get('DestinationStationName', '')),
                'items': [],
            }
            groups.append(by_key[key])

        by_key[key]['items'].append(item)

    return groups


def print_direction_table(direction_group):
    items = direction_group['items']
    print(f"{direction_group['label']}方向目前有{len(items)}筆資訊:")
    print_table(
        ['路線', '車站', '目的地', '預估到站', '服務狀態', '資料更新'],
        [
            [
                get_name_zh(item.get('LineName', '')) or item.get('LineID', ''),
                get_name_zh(item.get('StationName', '')),
                get_name_zh(item.get('DestinationStationName', '')),
                format_estimate_time(item),
                get_service_status(item),
                format_update_time(item.get('UpdateTime') or item.get('SrcUpdateTime')),
            ]
            for item in items
        ],
    )


def print_liveboard_tables(liveboards):
    if not liveboards:
        print('目前沒有捷運列車即將抵達')
        return

    first_item = liveboards[0]
    station_name = get_name_zh(first_item.get('StationName', ''))
    update_time = format_update_time(first_item.get('UpdateTime') or first_item.get('SrcUpdateTime'))
    direction_groups = group_liveboards_by_direction(liveboards)

    print(f'現在時間：{update_time}')
    print(f'{station_name}站目前有{len(liveboards)}筆捷運電子看板資訊，共{len(direction_groups)}個方向:')

    for index, direction_group in enumerate(direction_groups):
        if index:
            print('\n=================================\n')
        print_direction_table(direction_group)


def print_liveboard_table(liveboards):
    print_liveboard_tables(liveboards)


if __name__ == '__main__':
    tdx = TDX(client_id, client_secret)

    # MRT LiveBoard endpoint:
    # https://tdx.transportdata.tw/api/basic/v2/Rail/Metro/LiveBoard/TRTC/
    station_id = 'BL03'
    station_name = '土城'

    url = get_liveboard_url(station_id)
    try:
        response = tdx.get_response(url)
    except TDXRateLimitError as exc:
        print(exc)
        exit()
    except requests.HTTPError as exc:
        print(f'TDX API request failed: {exc}')
        exit()

    if not response:
        print(f'目前沒有捷運列車即將抵達{station_name}站')
        exit()

    print_liveboard_tables(response)
