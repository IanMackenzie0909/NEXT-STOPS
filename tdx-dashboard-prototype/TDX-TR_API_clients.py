import requests
import unicodedata
from datetime import datetime, time, timedelta


client_id = 'your_TDX_client_id'  # your_TDX_client_id
client_secret = 'your_TDX_client_secret'  # your_TDX_client_secret


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
        response = requests.post(token_url, headers=headers, data=data)
        # print(response.status_code)
        # print(response.json())
        return response.json()['access_token']

    def get_response(self, url):
        headers = {'authorization': f'Bearer {self.get_token()}'}
        response = requests.get(url, headers=headers)
        return response.json()


def get_station_name_zh(station_name):
    if isinstance(station_name, dict):
        return station_name.get('Zh_tw', '')
    return station_name


def parse_station_time(time_text, update_time_text):
    if not time_text or not update_time_text:
        return None

    update_time = datetime.fromisoformat(update_time_text)
    hour, minute, second = [int(part) for part in time_text.split(':')]
    station_time = datetime.combine(
        update_time.date(),
        time(hour, minute, second),
        tzinfo=update_time.tzinfo,
    )

    if station_time - update_time > timedelta(hours=12):
        station_time -= timedelta(days=1)
    elif update_time - station_time > timedelta(hours=12):
        station_time += timedelta(days=1)

    return station_time


def get_expected_time(item, field_name):
    station_time = parse_station_time(
        item.get(field_name),
        item.get('UpdateTime') or item.get('SrcUpdateTime'),
    )
    if station_time is None:
        return None
    return station_time + timedelta(minutes=int(item.get('DelayTime') or 0))


def format_delay(delay_time):
    delay_time = int(delay_time or 0)
    if delay_time == 0:
        return '準點'
    if delay_time > 0:
        return f'+{delay_time} 分'
    return f'{delay_time} 分'


def minutes_until(target_time, current_time):
    seconds = (target_time - current_time).total_seconds()
    return max(1, int((seconds + 59) // 60))


def get_train_status(item):
    current_time = datetime.fromisoformat(item.get('UpdateTime') or item.get('SrcUpdateTime'))
    arrival_time = get_expected_time(item, 'ScheduledArrivalTime')
    departure_time = get_expected_time(item, 'ScheduledDepartureTime')

    if arrival_time and current_time < arrival_time:
        minutes = minutes_until(arrival_time, current_time)
        if minutes <= 3:
            return f'即將進站（{minutes} 分後到站）'
        return f'{minutes} 分後到站'

    if arrival_time and (not departure_time or current_time < departure_time):
        if departure_time and departure_time - current_time <= timedelta(minutes=1):
            return '即將離站'
        if current_time - arrival_time >= timedelta(minutes=1):
            return '已靠站'
        if not departure_time:
            return '停靠中'
        minutes = minutes_until(departure_time, current_time)
        return f'停靠中，{minutes} 分後發車'

    if departure_time and current_time < departure_time:
        minutes = minutes_until(departure_time, current_time)
        return f'停靠中，{minutes} 分後發車'

    if departure_time and current_time - departure_time >= timedelta(minutes=1):
        return '已離站'
    return '可能已離站'


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


def print_train_table(direction_label, trains):
    station_name = get_station_name_zh(trains[0]['StationName'])
    update_time = datetime.fromisoformat(trains[0].get('UpdateTime') or trains[0].get('SrcUpdateTime'))
    print(f"現在時間：{update_time.strftime('%H:%M:%S')}")
    print(f"{direction_label}列車動態\n{station_name}站目前有{len(trains)}班次:")
    print_table(
        ['車次', '車站', '車種', '到站', '發車', '延誤', '狀態'],
        [
            [
                item['TrainNo'],
                get_station_name_zh(item['StationName']),
                item['TrainTypeID'],
                item['ScheduledArrivalTime'],
                item['ScheduledDepartureTime'],
                format_delay(item.get('DelayTime')),
                get_train_status(item),
            ]
            for item in trains
        ],
    )


if __name__ == '__main__':
    tdx = TDX(client_id, client_secret)

    # url = 'https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveBoard/Station/0900?$filter=Direction eq 1&$format=JSON'
    base_url = "https://tdx.transportdata.tw/api"
    # 取得指定[車站]列車即時到離站電子看板(動態前後30分鐘的車次)
    station_name = "臺中"
    endpoint = "/basic/v2/Rail/TRA/LiveBoard/Station/3300"

    direction_N = "Direction eq 0"  # 順逆行: [0:'順行', 1:'逆行']
    N_url = f"{base_url}{endpoint}?$filter={direction_N}&$format=JSON"

    direction_S = "Direction eq 1"  # 順逆行: [0:'順行', 1:'逆行']
    S_url = f"{base_url}{endpoint}?$filter={direction_S}&$format=JSON"

    response_N = tdx.get_response(N_url)
    response_S = tdx.get_response(S_url)

    if not response_N and not response_S:
        print(f"目前沒有列車即將抵達{station_name}站")
        exit()
    elif not response_N:
        print(f"目前沒有北上列車即將抵達{station_name}站")
        print()
        print_train_table("南下", response_S)
        exit()
    elif not response_S:
        print(f"目前沒有南下列車即將抵達{station_name}站")
        print()
        print_train_table("北上", response_N)
        exit()
    
    
    #   print(response)
    print_train_table("北上", response_N)
    print("\n=================================\n")
    print_train_table("南下", response_S)
