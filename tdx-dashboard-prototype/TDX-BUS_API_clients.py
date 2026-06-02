import math
import requests
import time
import unicodedata
from datetime import datetime
from urllib.parse import quote


client_id = 'your_TDX_client_id'  # your_TDX_client_id
client_secret = 'your_TDX_client_secret'  # your_TDX_client_secret

BASE_URL = 'https://tdx.transportdata.tw/api/basic/v2'
DEFAULT_CITY = 'Taipei'

STOP_STATUS = {
    0: '正常',
    1: '尚未發車',
    2: '交管不停靠',
    3: '末班車已過',
    4: '今日未營運',
}

DIRECTION_LABELS = {
    0: '去程',
    1: '返程',
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


def get_name_en(name):
    if isinstance(name, dict):
        return name.get('En', '')
    return ''


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def quote_filter(filter_text):
    return quote(filter_text, safe="'()/$,")


def get_station_url(city=DEFAULT_CITY):
    return f'{BASE_URL}/Bus/Station/City/{city}?$format=JSON'


def get_stop_url(city=DEFAULT_CITY, station_id=None):
    query = ['$format=JSON']
    if station_id:
        filter_text = f"StationID eq '{station_id}'"
        query.insert(0, f"$filter={quote_filter(filter_text)}")
    return f'{BASE_URL}/Bus/Stop/City/{city}?{"&".join(query)}'


def get_eta_url(city=DEFAULT_CITY, stop_uid=None, route_name=None):
    url = f'{BASE_URL}/Bus/EstimatedTimeOfArrival/City/{city}'
    query = ['$format=JSON', '$orderby=EstimateTime']

    filters = []
    if stop_uid:
        filters.append(f"StopUID eq '{stop_uid}'")
    if route_name:
        filters.append(f"RouteName/Zh_tw eq '{route_name}'")
    if filters:
        query.insert(0, f"$filter={quote_filter(' and '.join(filters))}")

    return f'{url}?{"&".join(query)}'


def get_stop_status(item):
    status_code = parse_int(item.get('StopStatus'))
    return STOP_STATUS.get(status_code, f'未知狀態({status_code})')


def get_direction_label(direction):
    return DIRECTION_LABELS.get(parse_int(direction, -1), f'方向{direction}')


def format_update_time(time_text):
    if not time_text:
        return ''

    try:
        return datetime.fromisoformat(time_text).strftime('%H:%M:%S')
    except ValueError:
        return time_text


def format_estimate_time(item):
    status_code = parse_int(item.get('StopStatus'))
    if status_code != 0:
        return get_stop_status(item)

    if item.get('EstimateTime') in (None, ''):
        return '無資料'

    estimate_seconds = parse_int(item.get('EstimateTime'))
    if estimate_seconds <= 0:
        return '進站中'
    if estimate_seconds < 60:
        return '1 分內'

    return f'{math.ceil(estimate_seconds / 60)} 分'


def get_arrival_status_kind(item):
    status_code = parse_int(item.get('StopStatus'))
    if status_code == 1:
        return 'pending'
    if status_code == 2:
        return 'skipping'
    if status_code in (3, 4):
        return 'closed'
    if status_code != 0:
        return 'muted'

    estimate_seconds = parse_int(item.get('EstimateTime'), 999999)
    if estimate_seconds <= 0:
        return 'arriving'
    if estimate_seconds <= 180:
        return 'approaching'
    return 'normal'


def get_position(item, field_name):
    position = item.get(field_name, {})
    return {
        'lat': position.get('PositionLat'),
        'lon': position.get('PositionLon'),
    }


def serialize_stop(stop):
    return {
        'uid': stop.get('StopUID', ''),
        'id': stop.get('StopID', ''),
        'name_zh': get_name_zh(stop.get('StopName', '')),
        'name_en': get_name_en(stop.get('StopName', '')),
        'station_id': stop.get('StationID', ''),
        'position': get_position(stop, 'StopPosition'),
        'route_name': get_name_zh(stop.get('RouteName', '')),
    }


def summarize_station_stops(stops):
    summaries = []
    by_key = {}

    for stop in stops:
        if not isinstance(stop, dict):
            continue

        summary = serialize_stop(stop)
        key = summary['uid'] or summary['id'] or summary['name_zh']
        if key not in by_key:
            summary['route_names'] = []
            summaries.append(summary)
            by_key[key] = summary

        route_name = summary.get('route_name')
        if route_name and route_name not in by_key[key]['route_names']:
            by_key[key]['route_names'].append(route_name)

    for summary in summaries:
        summary['route_count'] = len(summary['route_names'])

    return summaries


def serialize_station(station):
    stops = summarize_station_stops(station.get('Stops', []))
    route_names = sorted({
        get_name_zh(stop.get('RouteName', ''))
        for stop in station.get('Stops', [])
        if isinstance(stop, dict) and get_name_zh(stop.get('RouteName', ''))
    })

    return {
        'uid': station.get('StationUID', ''),
        'id': station.get('StationID', ''),
        'name_zh': get_name_zh(station.get('StationName', '')),
        'name_en': get_name_en(station.get('StationName', '')),
        'address': station.get('StationAddress', ''),
        'position': get_position(station, 'StationPosition'),
        'stops': stops,
        'route_names': route_names,
        'stop_count': len(stops),
        'route_count': len(route_names),
    }


def serialize_arrival(item):
    return {
        'route_uid': item.get('RouteUID', ''),
        'route_id': item.get('RouteID', ''),
        'route_name': get_name_zh(item.get('RouteName', '')),
        'subroute_name': get_name_zh(item.get('SubRouteName', '')),
        'direction': item.get('Direction'),
        'direction_label': get_direction_label(item.get('Direction')),
        'stop_uid': item.get('StopUID', ''),
        'stop_id': item.get('StopID', ''),
        'stop_name': get_name_zh(item.get('StopName', '')),
        'stop_sequence': item.get('StopSequence', ''),
        'estimate_seconds': item.get('EstimateTime'),
        'estimate_label': format_estimate_time(item),
        'stop_status_code': parse_int(item.get('StopStatus')),
        'stop_status': get_stop_status(item),
        'status_kind': get_arrival_status_kind(item),
        'plate_number': item.get('PlateNumb', ''),
        'next_bus_time': item.get('NextBusTime', ''),
        'update_time': item.get('UpdateTime') or item.get('SrcUpdateTime') or '',
    }


def sort_arrival_item(item):
    status_code = parse_int(item.get('StopStatus'))
    estimate_seconds = parse_int(item.get('EstimateTime'), 999999)
    return (
        status_code != 0,
        estimate_seconds,
        get_name_zh(item.get('RouteName', '')),
        parse_int(item.get('Direction'), 0),
    )


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


def print_arrival_table(arrivals):
    if not arrivals:
        print('目前沒有公車到站資訊')
        return

    first_item = arrivals[0]
    stop_name = get_name_zh(first_item.get('StopName', ''))
    update_time = format_update_time(first_item.get('UpdateTime') or first_item.get('SrcUpdateTime'))

    print(f'現在時間：{update_time}')
    print(f'{stop_name}站牌目前有{len(arrivals)}筆公車到站資訊:')
    print_table(
        ['路線', '方向', '站序', '預估到站', '狀態', '車牌', '資料更新'],
        [
            [
                get_name_zh(item.get('RouteName', '')),
                get_direction_label(item.get('Direction')),
                item.get('StopSequence', ''),
                format_estimate_time(item),
                get_stop_status(item),
                item.get('PlateNumb', ''),
                format_update_time(item.get('UpdateTime') or item.get('SrcUpdateTime')),
            ]
            for item in sorted(arrivals, key=sort_arrival_item)
        ],
    )


if __name__ == '__main__':
    tdx = TDX(client_id, client_secret)

    city = DEFAULT_CITY
    stop_uid = 'TPE11679'

    url = get_eta_url(city, stop_uid=stop_uid)
    try:
        response = tdx.get_response(url)
    except TDXRateLimitError as exc:
        print(exc)
        exit()
    except requests.HTTPError as exc:
        print(f'TDX API request failed: {exc}')
        exit()

    print_arrival_table(response)
