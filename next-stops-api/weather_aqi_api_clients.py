"""整合中央氣象署天氣、紫外線與環境部空氣品質資料的 client。

這個檔案不是獨立 HTTP server，而是被 next-stops-api/server.py 匯入。
server.py 的 /api/context 會呼叫這裡的 get_context(lat, lon)，再把整理好的
天氣、雨量、紫外線、AQI 與戶外舒適度回傳給前端。
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent

# 外部 API 與資料集代碼集中放在這裡，之後要替換資料來源時比較容易維護。
CWA_DATASTORE_BASE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
MOENV_AQI_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_432"
CWA_CURRENT_WEATHER_DATASET = "O-A0001-001"
CWA_10MIN_RAIN_DATASET = "O-A0003-001"
CWA_UV_DATASET = "O-A0005-001"
CWA_36H_FORECAST_DATASET = "F-C0032-001"
CWA_TAIPEI_TOWNSHIP_FORECAST_DATASET = "F-D0047-061"
CWA_TOWNSHIP_ELEMENT_NAMES = "溫度,相對濕度,3小時降雨機率,風速,天氣現象"
DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_FORECAST_LOCATION = "臺北市"


def load_root_env():
    """讀取專案根目錄的 .env，讓直接執行本檔或 server.py 都能拿到 API key。"""
    env_path = ROOT.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_root_env()


# -----------------------------------------------------------------------------
# 基礎資料整理工具
# -----------------------------------------------------------------------------

def normalize(value):
    """把任意值轉成小寫字串，主要用於寬鬆比對欄位名稱或狀態文字。"""
    return str(value or "").strip().lower()


def parse_int(value, default=0):
    """安全轉整數；轉換失敗時回傳 default，避免 API 缺值讓整段流程中斷。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value, default=None):
    """安全轉浮點數；座標與氣象數值常用這個函式處理。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_list(value):
    """把單一值或 None 正規化成 list，方便處理 API 有時回物件、有時回陣列的格式。"""
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def deep_get(data, paths, default=None):
    """依序嘗試多組巢狀路徑，取出第一個存在且非空的值。"""
    for path in paths:
        current = data
        ok = True
        for part in path:
            if isinstance(part, int):
                if not isinstance(current, list) or len(current) <= part:
                    ok = False
                    break
                current = current[part]
            elif isinstance(current, dict) and part in current:
                current = current[part]
            else:
                ok = False
                break
        if ok and current not in (None, ""):
            return current
    return default


def normalize_number(value):
    """把 CWA/MOENV 常見的缺值標記轉成 None，其餘值轉成 float。"""
    if value in (None, "", "-", "X", "x", "-99", "-99.0", "-999", "-999.0"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number in (-99, -999):
        return None
    return number


def normalize_text(value):
    """把文字欄位去空白，並把 API 缺值標記轉成空字串。"""
    text = str(value or "").strip()
    if text in ("", "-", "X", "x", "-99", "-99.0", "-999", "-999.0"):
        return ""
    return text


def flatten_pairs(value, prefix=""):
    """把巢狀 dict/list 攤平成 path/value，用於不確定欄位名稱時的 keyword 搜尋。"""
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from flatten_pairs(item, path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]"
            yield from flatten_pairs(item, path)
        return
    yield prefix, value


def find_number_by_keywords(data, include_keywords, exclude_keywords=None):
    """在整份巢狀資料中用欄位路徑 keyword 找第一個可用數值。"""
    exclude_keywords = exclude_keywords or []
    for path, value in flatten_pairs(data):
        haystack = normalize(path).replace("_", "").replace("-", "")
        if any(keyword in haystack for keyword in include_keywords) and not any(keyword in haystack for keyword in exclude_keywords):
            number = normalize_number(value)
            if number is not None:
                return number
    return None


def find_text_by_keywords(data, include_keywords):
    """在整份巢狀資料中用欄位路徑 keyword 找第一個可用文字。"""
    for path, value in flatten_pairs(data):
        haystack = normalize(path).replace("_", "").replace("-", "")
        if any(keyword in haystack for keyword in include_keywords):
            text = normalize_text(value)
            if text and normalize_number(text) is None:
                return text
    return ""


def haversine_meters(lat1, lon1, lat2, lon2):
    """用 haversine 公式計算兩個經緯度點的球面距離，單位是公尺。"""
    radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def uv_exposure_level(uv_index):
    """當 CWA 沒提供紫外線暴露等級文字時，用 UV index 推估標準等級。"""
    if uv_index is None:
        return ""
    if uv_index <= 2:
        return "low"
    if uv_index <= 5:
        return "moderate"
    if uv_index <= 7:
        return "high"
    if uv_index <= 10:
        return "very_high"
    return "extreme"


# -----------------------------------------------------------------------------
# 座標、最近站點與 CWA/MOENV 回應格式 parser
# -----------------------------------------------------------------------------

def station_coordinates(item):
    """從 CWA 觀測站資料中抽出測站座標，支援多種新舊欄位命名。"""
    lat = deep_get(item, [
        ("GeoInfo", "Coordinates", 0, "StationLatitude"),
        ("GeoInfo", "Coordinates", 0, "Latitude"),
        ("GeoInfo", "StationLatitude"),
        ("GeoInfo", "Coordinates", "StationLatitude"),
        ("GeoInfo", "Coordinates", "Latitude"),
        ("Latitude",),
        ("StationLatitude",),
        ("lat",),
    ])
    lon = deep_get(item, [
        ("GeoInfo", "Coordinates", 0, "StationLongitude"),
        ("GeoInfo", "Coordinates", 0, "Longitude"),
        ("GeoInfo", "StationLongitude"),
        ("GeoInfo", "Coordinates", "StationLongitude"),
        ("GeoInfo", "Coordinates", "Longitude"),
        ("Longitude",),
        ("StationLongitude",),
        ("lon",),
        ("lng",),
    ])
    lat = normalize_number(lat)
    lon = normalize_number(lon)
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon}


def township_coordinates(item):
    """從鄉鎮預報的行政區資料中抽出代表點座標。"""
    lat = normalize_number(item.get("Latitude") or item.get("latitude") or item.get("lat"))
    lon = normalize_number(item.get("Longitude") or item.get("longitude") or item.get("lon") or item.get("lng"))
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon}


def nearest_item(items, lat, lon, coordinate_getter):
    """在資料清單中找出距離使用者座標最近且有座標的項目。"""
    best = None
    for item in items:
        position = coordinate_getter(item)
        if not position:
            continue
        distance = haversine_meters(lat, lon, position["lat"], position["lon"])
        if best is None or distance < best["distance_meters"]:
            best = {
                "item": item,
                "position": position,
                "distance_meters": round(distance),
            }
    return best


def cwa_uv_records(payload):
    """整理 CWA 紫外線資料格式，把外層 Date/elementName 補進每筆測站資料。"""
    weather_element = deep_get(payload, [
        ("records", "weatherElement"),
        ("records", "WeatherElement"),
    ], {})
    locations = (
        weather_element.get("location")
        or weather_element.get("Location")
        or weather_element.get("locations")
        or []
    ) if isinstance(weather_element, dict) else []
    date = weather_element.get("Date", "") if isinstance(weather_element, dict) else ""
    element_name = weather_element.get("elementName", "") if isinstance(weather_element, dict) else ""

    records = []
    for item in as_list(locations):
        if not isinstance(item, dict):
            continue
        record = dict(item)
        record.setdefault("Date", date)
        record.setdefault("elementName", element_name)
        records.append(record)
    return records


def cwa_township_records(payload):
    """整理 F-D0047 鄉鎮預報格式，攤平成行政區 location 清單。"""
    records = payload.get("records", {}) if isinstance(payload, dict) else {}
    groups = records.get("Locations") or records.get("locations") or []
    result = []
    for group in as_list(groups):
        if not isinstance(group, dict):
            continue
        group_name = group.get("LocationsName") or group.get("locationsName") or group.get("DatasetDescription") or ""
        for item in as_list(group.get("Location") or group.get("location")):
            if not isinstance(item, dict):
                continue
            record = dict(item)
            record.setdefault("locationsName", group_name)
            result.append(record)
    return result


def cwa_station_name(item):
    """從 CWA 觀測資料中抓測站名稱；沒有名稱時退回站號。"""
    return normalize_text(
        item.get("StationName")
        or item.get("locationName")
        or item.get("LocationName")
        or item.get("StationId")
        or item.get("StationID")
        or ""
    )


def cwa_township_name(item):
    """從鄉鎮預報資料中抓行政區名稱；沒有名稱時退回 geocode。"""
    return normalize_text(item.get("LocationName") or item.get("locationName") or item.get("Geocode") or "")


def cwa_weather_element(item):
    """把 CWA WeatherElement 正規化成 dict，讓後續可以用欄位名直接取值。"""
    element = item.get("WeatherElement") or item.get("weatherElement") or {}
    if isinstance(element, dict):
        return element
    result = {}
    for entry in as_list(element):
        name = entry.get("elementName") or entry.get("ElementName")
        value = entry.get("elementValue") or entry.get("ElementValue")
        if isinstance(value, list):
            value = deep_get(value[0], [("value",), ("Value",)], value[0])
        elif isinstance(value, dict):
            value = deep_get(value, [("value",), ("Value",)], value)
        if name:
            result[name] = value
    return result


def cwa_forecast_elements(item):
    """取得預報資料的 WeatherElement 陣列，並處理單筆/多筆格式差異。"""
    elements = item.get("WeatherElement") or item.get("weatherElement") or []
    return as_list(elements)


def parse_cwa_datetime(value):
    """解析 CWA ISO 時間字串；若來源沒有時區，保守補 UTC。"""
    text = normalize_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def select_forecast_time(times, now=None):
    """從預報時間序列中選出最接近現在的時間點，優先選未來最近一筆。"""
    now = now or datetime.now(timezone.utc)
    future = None
    latest_past = None
    first_usable = None
    for item in as_list(times):
        if not isinstance(item, dict):
            continue
        ref_time = parse_cwa_datetime(item.get("DataTime") or item.get("StartTime") or item.get("startTime"))
        if not ref_time:
            continue
        if first_usable is None:
            first_usable = (ref_time, item)
        if ref_time >= now and (future is None or ref_time < future[0]):
            future = (ref_time, item)
        if ref_time <= now and (latest_past is None or ref_time > latest_past[0]):
            latest_past = (ref_time, item)
    selected = future or latest_past or first_usable
    return selected[1] if selected else {}


def first_forecast_value(time_item):
    """從單一預報時間點取出第一個 ElementValue。"""
    value = deep_get(time_item, [
        ("ElementValue", 0),
        ("elementValue", 0),
        ("ElementValue",),
        ("elementValue",),
    ], {})
    if isinstance(value, dict):
        return value
    return {"value": value}


def aqi_coordinates(item):
    """從環境部 AQI 測站資料中抽出座標。"""
    lat = normalize_number(item.get("latitude") or item.get("Latitude") or item.get("lat"))
    lon = normalize_number(item.get("longitude") or item.get("Longitude") or item.get("lon") or item.get("lng"))
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon}


def first_usable_aqi_record(records):
    """當找不到最近 AQI 站時，退回第一筆有 AQI 數值的資料。"""
    for item in records:
        if parse_int(item.get("aqi") or item.get("AQI"), None) is not None:
            return item
    return records[0] if records else None


def first_usable_uv_record(records):
    """當找不到最近 UV 站時，退回第一筆有 UV 數值的資料。"""
    for item in records:
        element = cwa_weather_element(item)
        uv_value = (
            normalize_number(
                element.get("UVIndex")
                or element.get("UVI")
                or item.get("UVIndex")
                or item.get("UVI")
                or item.get("UV")
            )
            or find_number_by_keywords(item, ["uvindex", "uvi", "uv", "紫外線"], ["longitude", "latitude"])
        )
        if uv_value is not None:
            return item
    return records[0] if records else None


def uv_record_by_station_id(records, station_id):
    """優先用即時天氣觀測站同站號的 UV 資料，讓來源位置盡量一致。"""
    station_id = normalize_text(station_id)
    if not station_id:
        return None
    for item in records:
        item_station_id = normalize_text(item.get("StationID") or item.get("StationId") or item.get("stationID"))
        if item_station_id != station_id:
            continue
        uv_value = (
            normalize_number(item.get("UVIndex") or item.get("UVI") or item.get("UV"))
            or find_number_by_keywords(item, ["uvindex", "uvi", "uv", "紫外線"], ["longitude", "latitude"])
        )
        if uv_value is not None:
            return item
    return None


class WeatherAQIClient:
    """封裝所有外部天氣/AQI API 呼叫與資料合併邏輯。"""

    def __init__(self, cwa_api_key=None, aqi_api_key=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, forecast_location=None):
        """建立 client，優先使用傳入 key，否則從 .env / 環境變數讀取。"""
        self.cwa_api_key = cwa_api_key or os.getenv("CWA_API_KEY") or os.getenv("WEATHER_API_KEY") or ""
        self.aqi_api_key = aqi_api_key or os.getenv("AQI_API_KEY") or os.getenv("MOENV_API_KEY") or ""
        self.timeout_seconds = timeout_seconds
        self.forecast_location = forecast_location or os.getenv("CWA_FORECAST_LOCATION", DEFAULT_FORECAST_LOCATION)

    def fetch_json(self, url, params):
        """送出 GET request 並解析 JSON；所有 CWA/MOENV 呼叫最後都會走這裡。"""
        if params:
            url = f"{url}?{urlencode(params)}"
        with urlopen(url, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def cwa_records(self, dataset, extra_params=None):
        """呼叫 CWA datastore，並依不同資料集整理成統一的 records list。"""
        if not self.cwa_api_key:
            raise RuntimeError("CWA_API_KEY or WEATHER_API_KEY is not configured")
        params = {
            "Authorization": self.cwa_api_key,
            "format": "JSON",
        }
        if extra_params:
            params.update(extra_params)
        payload = self.fetch_json(f"{CWA_DATASTORE_BASE}/{dataset}", params)
        # CWA 各資料集 JSON 結構不完全一致，所以特殊格式先分流處理。
        if dataset == CWA_UV_DATASET:
            return cwa_uv_records(payload)
        if dataset == CWA_TAIPEI_TOWNSHIP_FORECAST_DATASET:
            return cwa_township_records(payload)
        records = payload.get("records", {})
        if isinstance(records, list):
            return records
        return (
            records.get("Station")
            or records.get("station")
            or cwa_township_records(payload)
            or records.get("location")
            or records.get("Location")
            or []
        )

    def current_weather(self, lat, lon):
        """取得最近 CWA 自動氣象站的即時天氣觀測資料。"""
        records = self.cwa_records(CWA_CURRENT_WEATHER_DATASET)
        nearest = nearest_item(records, lat, lon, station_coordinates)
        if not nearest:
            raise RuntimeError("CWA current weather returned no station with coordinates")
        item = nearest["item"]
        element = cwa_weather_element(item)
        # 觀測資料可能只有天氣描述，也可能是 WeatherElement 中的 Weather 欄位。
        weather = (
            element.get("Weather")
            or element.get("weather")
            or element.get("WeatherDescription")
            or ""
        )
        weather = normalize_text(weather)
        return {
            "station": cwa_station_name(item),
            "station_id": item.get("StationID") or item.get("StationId") or item.get("stationID") or "",
            "station_distance_meters": nearest["distance_meters"],
            "observation_time": deep_get(item, [
                ("ObsTime", "DateTime"),
                ("ObsTime", "obsTime"),
                ("obsTime",),
                ("time", "obsTime"),
            ], ""),
            "weather": weather,
            "temperature_c": normalize_number(element.get("AirTemperature") or element.get("TEMP") or element.get("Temperature")),
            "relative_humidity": normalize_number(element.get("RelativeHumidity") or element.get("HUMD")),
            "wind_speed_mps": normalize_number(element.get("WindSpeed") or element.get("WDSD")),
            "wind_direction_degrees": normalize_number(element.get("WindDirection") or element.get("WDIR")),
            "pressure_hpa": normalize_number(element.get("AirPressure") or element.get("PRES")),
        }

    def rainfall(self, lat, lon):
        """取得最近 CWA 雨量站的 10 分鐘、即時與 1 小時雨量。"""
        records = self.cwa_records(CWA_10MIN_RAIN_DATASET)
        nearest = nearest_item(records, lat, lon, station_coordinates)
        if not nearest:
            raise RuntimeError("CWA rainfall returned no station with coordinates")
        item = nearest["item"]
        rainfall = item.get("RainfallElement") or item.get("rainfallElement") or {}
        return {
            "station": cwa_station_name(item),
            "station_distance_meters": nearest["distance_meters"],
            # 不同版本資料欄位大小寫略有差異，因此 deep_get 同時嘗試多個路徑。
            "precipitation_10min_mm": normalize_number(deep_get(rainfall, [
                ("Past10Min", "Precipitation"),
                ("past10Min", "precipitation"),
                ("Past10Min",),
            ])),
            "precipitation_now_mm": normalize_number(deep_get(rainfall, [
                ("Now", "Precipitation"),
                ("now", "precipitation"),
                ("Now",),
            ])),
            "precipitation_1hr_mm": normalize_number(deep_get(rainfall, [
                ("Past1hr", "Precipitation"),
                ("Past1Hr", "Precipitation"),
                ("past1hr", "precipitation"),
                ("Past1hr",),
            ])),
        }

    def uv(self, lat, lon, station_id=""):
        """取得紫外線資料；若可行會優先使用和即時天氣同站號的資料。"""
        records = self.cwa_records(CWA_UV_DATASET)
        nearest = nearest_item(records, lat, lon, station_coordinates)
        item = uv_record_by_station_id(records, station_id) if station_id else None
        if not item:
            item = nearest["item"] if nearest else first_usable_uv_record(records)
        if not item:
            raise RuntimeError("CWA UV returned no usable record")
        element = cwa_weather_element(item)
        # UV 資料欄位名稱在不同回應中不完全一致，先列常見欄位，再用 keyword 補抓。
        uv_index = (
            normalize_number(
                element.get("UVIndex")
                or element.get("UVI")
                or item.get("UVIndex")
                or item.get("UVI")
                or item.get("UV")
            )
            or find_number_by_keywords(item, ["uvindex", "uvi", "uv", "紫外線"], ["longitude", "latitude"])
        )
        # 若 API 沒有暴露等級文字，就根據 UV index 用 uv_exposure_level() 推估。
        exposure_level = (
            normalize_text(
                element.get("UVExposureLevel")
                or element.get("ExposureLevel")
                or item.get("UVExposureLevel")
                or item.get("ExposureLevel")
                or ""
            )
            or find_text_by_keywords(item, ["exposure", "level", "曝曬", "級"])
            or uv_exposure_level(uv_index)
        )
        return {
            "station": cwa_station_name(item),
            "station_id": item.get("StationID") or item.get("StationId") or item.get("stationID") or "",
            "station_distance_meters": nearest["distance_meters"] if nearest else None,
            "uv_index": uv_index,
            "exposure_level": exposure_level,
            "observation_time": deep_get(item, [
                ("ObsTime", "DateTime"),
                ("obsTime",),
                ("time", "obsTime"),
                ("Date",),
            ], ""),
        }

    def forecast(self):
        """取得縣市層級 36 小時預報，作為較粗粒度的備援預報資料。"""
        records = self.cwa_records(CWA_36H_FORECAST_DATASET, {"locationName": self.forecast_location})
        location = records[0] if records else {}
        elements = location.get("weatherElement", []) or location.get("WeatherElement", [])
        result = {
            "location": location.get("locationName") or self.forecast_location,
            "rain_probability": None,
            "weather": "",
            "min_temperature_c": None,
            "max_temperature_c": None,
            "start_time": "",
            "end_time": "",
        }
        for element in elements:
            name = element.get("elementName")
            # F-C0032 的每個 WeatherElement 都有多個 time；這裡只取最近一段。
            first_time = as_list(element.get("time"))[0] if as_list(element.get("time")) else {}
            value = deep_get(first_time, [
                ("parameter", "parameterName"),
                ("elementValue", 0, "value"),
                ("elementValue", "value"),
            ])
            if not result["start_time"]:
                result["start_time"] = first_time.get("startTime", "")
                result["end_time"] = first_time.get("endTime", "")
            if name == "PoP":
                pop = normalize_number(value)
                result["rain_probability"] = pop / 100 if pop is not None else None
            elif name == "Wx":
                result["weather"] = normalize_text(value)
            elif name == "MinT":
                result["min_temperature_c"] = normalize_number(value)
            elif name == "MaxT":
                result["max_temperature_c"] = normalize_number(value)
        return result

    def township_forecast(self, lat, lon):
        """取得臺北市行政區層級預報，補足測站停擺或資料缺值時的溫度/濕度/風等欄位。"""
        records = self.cwa_records(CWA_TAIPEI_TOWNSHIP_FORECAST_DATASET, {
            "ElementName": CWA_TOWNSHIP_ELEMENT_NAMES,
        })
        # F-D0047 提供各行政區代表點座標，這裡用最近行政區代表點對應輸入座標。
        nearest = nearest_item(records, lat, lon, township_coordinates)
        if not nearest:
            raise RuntimeError("CWA township forecast returned no location with coordinates")

        item = nearest["item"]
        result = {
            "location": cwa_township_name(item),
            "geocode": item.get("Geocode") or item.get("geocode") or "",
            "location_distance_meters": nearest["distance_meters"],
            "weather": "",
            "temperature_c": None,
            "relative_humidity": None,
            "rain_probability": None,
            "wind_speed_mps": None,
            "data_time": "",
            "start_time": "",
            "end_time": "",
            "source": "CWA township forecast",
        }

        for element in cwa_forecast_elements(item):
            # 每個 element 有自己的時間序列；逐一選出最接近現在的時間點。
            time_item = select_forecast_time(element.get("Time") or element.get("time"))
            if not time_item:
                continue
            if not result["data_time"]:
                result["data_time"] = time_item.get("DataTime", "") or time_item.get("dataTime", "")
                result["start_time"] = time_item.get("StartTime", "") or time_item.get("startTime", "")
                result["end_time"] = time_item.get("EndTime", "") or time_item.get("endTime", "")

            value = first_forecast_value(time_item)
            # 根據 ElementValue 實際存在的 key 判斷是哪一種氣象元素。
            if "Temperature" in value:
                result["temperature_c"] = normalize_number(value.get("Temperature"))
            if "RelativeHumidity" in value:
                result["relative_humidity"] = normalize_number(value.get("RelativeHumidity"))
            if "ProbabilityOfPrecipitation" in value:
                pop = normalize_number(value.get("ProbabilityOfPrecipitation"))
                result["rain_probability"] = pop / 100 if pop is not None else None
            if "WindSpeed" in value:
                result["wind_speed_mps"] = normalize_number(value.get("WindSpeed"))
            if "Weather" in value:
                result["weather"] = normalize_text(value.get("Weather"))

        return result

    def aqi(self, lat, lon):
        """取得環境部 AQI 資料，並選出離輸入座標最近的空品測站。"""
        if not self.aqi_api_key:
            raise RuntimeError("AQI_API_KEY or MOENV_API_KEY is not configured")
        payload = self.fetch_json(MOENV_AQI_URL, {
            "api_key": self.aqi_api_key,
            "format": "json",
            "limit": 1000,
        })
        records = payload.get("records", []) if isinstance(payload, dict) else payload
        if isinstance(records, dict):
            records = records.get("records", []) or records.get("data", []) or []
        if not isinstance(records, list):
            raise RuntimeError("MOENV AQI returned unexpected records format")
        # AQI 站點比氣象站稀疏；找不到座標最近站時再退回第一筆可用 AQI。
        nearest = nearest_item(records, lat, lon, aqi_coordinates)
        item = nearest["item"] if nearest else first_usable_aqi_record(records)
        if not item:
            raise RuntimeError("MOENV AQI returned no usable record")
        return {
            "site": normalize_text(item.get("sitename") or item.get("SiteName") or ""),
            "county": normalize_text(item.get("county") or item.get("County") or ""),
            "station_distance_meters": nearest["distance_meters"] if nearest else None,
            "aqi": parse_int(item.get("aqi") or item.get("AQI"), None),
            "status": normalize_text(item.get("status") or item.get("Status") or ""),
            "pollutant": normalize_text(item.get("pollutant") or item.get("Pollutant") or ""),
            "pm25": normalize_number(item.get("pm2.5") or item.get("PM2.5") or item.get("pm2.5_avg") or item.get("PM2.5_AVG")),
            "pm10": normalize_number(item.get("pm10") or item.get("PM10") or item.get("pm10_avg") or item.get("PM10_AVG")),
            "wind_speed_mps": normalize_number(item.get("wind_speed") or item.get("WIND_SPEED")),
            "wind_direction_degrees": normalize_number(item.get("wind_direc") or item.get("WIND_DIREC")),
            "publish_time": normalize_text(item.get("publishtime") or item.get("PublishTime") or ""),
        }

    def real_context(self, lat, lon):
        """取得真實外部資料並合併成前端需要的 context JSON。"""
        # 每個來源獨立記錄錯誤；單一 API 失敗時不讓整個 context 直接失敗。
        errors = {}
        current = {}
        rainfall = {}
        uv = {}
        forecast = {}
        township_forecast = {}
        aqi = {}

        # 依序呼叫各資料來源。UV 會嘗試沿用 current_weather 的 station_id，
        # 所以 current_weather 放在 uv 前面。
        for label, loader in [
            ("current_weather", lambda: self.current_weather(lat, lon)),
            ("rainfall_10min", lambda: self.rainfall(lat, lon)),
            ("uv", lambda: self.uv(lat, lon, current.get("station_id", ""))),
            ("forecast_36h", self.forecast),
            ("township_forecast", lambda: self.township_forecast(lat, lon)),
            ("aqi", lambda: self.aqi(lat, lon)),
        ]:
            try:
                value = loader()
                if label == "current_weather":
                    current = value
                elif label == "rainfall_10min":
                    rainfall = value
                elif label == "uv":
                    uv = value
                elif label == "forecast_36h":
                    forecast = value
                elif label == "township_forecast":
                    township_forecast = value
                elif label == "aqi":
                    aqi = value
            except Exception as exc:
                errors[label] = str(exc)

        # 有些 UV 回應只有站號或資料值，這裡補上即時觀測站名稱，讓前端顯示更完整。
        if uv and current.get("station") and not uv.get("station"):
            uv["station"] = current.get("station")

        # 如果所有外部資料都失敗，才往上丟錯，交給 context() 使用 heuristic fallback。
        if not current and not aqi and not forecast and not township_forecast and not rainfall and not uv:
            raise RuntimeError("; ".join(errors.values()) or "No external context data available")

        # 降雨機率優先用行政區預報，其次縣市 36 小時預報；若都沒有，用最近雨量推估。
        rain_probability = township_forecast.get("rain_probability")
        if rain_probability is None:
            rain_probability = forecast.get("rain_probability")
        if rain_probability is None:
            rain_10min = rainfall.get("precipitation_10min_mm") or 0
            rain_probability = min(0.95, 0.15 + rain_10min / 10)

        # AQI 狀態保留 API 原文；若沒有狀態文字，根據數值粗略分類。
        aqi_value = aqi.get("aqi")
        aqi_status = aqi.get("status") or ("good" if aqi_value and aqi_value <= 50 else "moderate" if aqi_value and aqi_value <= 100 else "unknown")

        # 氣溫、濕度、風速採觀測優先；觀測缺值時才用行政區預報補。
        temperature = current.get("temperature_c")
        if temperature is None:
            temperature = township_forecast.get("temperature_c")
        relative_humidity = current.get("relative_humidity")
        if relative_humidity is None:
            relative_humidity = township_forecast.get("relative_humidity")
        wind_speed = current.get("wind_speed_mps")
        if wind_speed is None:
            wind_speed = township_forecast.get("wind_speed_mps")
        if wind_speed is None:
            wind_speed = aqi.get("wind_speed_mps")
        wind_direction = current.get("wind_direction_degrees") if current.get("wind_direction_degrees") is not None else aqi.get("wind_direction_degrees")
        uv_index = uv.get("uv_index")

        # 天氣現象文字採即時觀測優先，再退到行政區與縣市預報。
        weather_text = current.get("weather") or township_forecast.get("weather") or forecast.get("weather") or ""
        used_township_fallback = bool(township_forecast) and (
            current.get("temperature_c") is None
            or current.get("relative_humidity") is None
            or current.get("wind_speed_mps") is None
            or not current.get("weather")
            or township_forecast.get("rain_probability") is not None
        )
        weather_source = "CWA observation + township forecast fallback" if used_township_fallback else "CWA Open Data"

        # 將多個指標壓成前端可直接使用的戶外舒適度狀態。
        outdoor_comfort = "comfortable"
        if rain_probability >= 0.5 or (rainfall.get("precipitation_10min_mm") or 0) > 0:
            outdoor_comfort = "rain_risk"
        elif aqi_value and aqi_value > 100:
            outdoor_comfort = "poor_air_quality"
        elif uv_index and uv_index >= 11:
            outdoor_comfort = "extreme_uv"
        elif uv_index and uv_index >= 8:
            outdoor_comfort = "very_high_uv"
        elif uv_index and uv_index >= 6:
            outdoor_comfort = "high_uv"
        elif temperature and temperature >= 30:
            outdoor_comfort = "hot"
        elif wind_speed and wind_speed >= 10:
            outdoor_comfort = "windy"

        # summary 是給卡片或列表快速顯示的短句，詳細數值仍保留在各欄位。
        summary_parts = []
        if weather_text:
            summary_parts.append(weather_text)
        if temperature is not None:
            summary_parts.append(f"{temperature}C")
        summary_parts.append(f"rain risk {round(rain_probability * 100)}%")
        if wind_speed is not None:
            summary_parts.append(f"wind {wind_speed} m/s")

        # 最終輸出結構刻意固定，讓前端不需要知道每個外部 API 的原始格式。
        return {
            "location": {"lat": lat, "lon": lon},
            "weather": {
                "summary": ", ".join(summary_parts),
                "weather": weather_text,
                "temperature_c": temperature,
                "relative_humidity": relative_humidity,
                "rain_probability": rain_probability,
                "precipitation_10min_mm": rainfall.get("precipitation_10min_mm"),
                "precipitation_1hr_mm": rainfall.get("precipitation_1hr_mm"),
                "wind_speed_mps": wind_speed,
                "wind_direction_degrees": wind_direction,
                "pressure_hpa": current.get("pressure_hpa"),
                "forecast": forecast,
                "township_forecast": township_forecast,
                "source": weather_source,
                "station": current.get("station"),
                "rain_station": rainfall.get("station"),
                "forecast_location": township_forecast.get("location") or forecast.get("location"),
                "observation_time": current.get("observation_time"),
            },
            "uv": {
                "uv_index": uv_index,
                "exposure_level": uv.get("exposure_level"),
                "station": uv.get("station"),
                "source": "CWA Open Data",
            },
            "air_quality": {
                "aqi": aqi_value,
                "status": aqi_status,
                "pollutant": aqi.get("pollutant"),
                "pm25": aqi.get("pm25"),
                "pm10": aqi.get("pm10"),
                "site": aqi.get("site"),
                "county": aqi.get("county"),
                "publish_time": aqi.get("publish_time"),
                "source": "MOENV Open Data",
            },
            "outdoor_comfort": outdoor_comfort,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_status": {
                "mode": "external",
                "errors": errors,
            },
        }

    def heuristic_context(self, lat, lon, fallback_error=""):
        """外部 API 無法使用時的原型 fallback，避免前端完全沒有資料可顯示。"""
        # 用座標產生穩定的 pseudo-random seed，同一地點會得到一致的模擬資料。
        seed = abs(math.sin(lat * 12.9898 + lon * 78.233))
        temperature = round(21 + seed * 8, 1)
        rain_probability = round(0.12 + (seed * 0.42), 2)
        aqi_value = int(35 + seed * 55)
        aqi_status = "good" if aqi_value <= 50 else "moderate" if aqi_value <= 100 else "poor"
        outdoor_comfort = "comfortable"
        # 原型狀態只做粗略判斷，明確標記 source 為 prototype heuristic。
        if rain_probability > 0.45:
            outdoor_comfort = "rain_risk"
        elif aqi_value > 80:
            outdoor_comfort = "air_quality_watch"
        elif temperature > 27:
            outdoor_comfort = "warm"

        return {
            "location": {"lat": lat, "lon": lon},
            "weather": {
                "summary": f"{temperature}C, rain risk {round(rain_probability * 100)}%",
                "weather": "",
                "temperature_c": temperature,
                "relative_humidity": None,
                "rain_probability": rain_probability,
                "precipitation_10min_mm": None,
                "precipitation_1hr_mm": None,
                "wind_speed_mps": None,
                "wind_direction_degrees": None,
                "pressure_hpa": None,
                "forecast": {},
                "source": "prototype heuristic",
            },
            "air_quality": {
                "aqi": aqi_value,
                "status": aqi_status,
                "pollutant": None,
                "pm25": None,
                "pm10": None,
                "source": "prototype heuristic",
            },
            "uv": {
                "uv_index": None,
                "exposure_level": None,
                "source": "prototype heuristic",
            },
            "outdoor_comfort": outdoor_comfort,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_status": {
                "mode": "heuristic_fallback",
                "error": fallback_error,
            },
            "note": "Using heuristic fallback because external Weather/AQI APIs are not configured or failed.",
        }

    def context(self, lat, lon):
        """公開入口：先取真實資料，失敗時自動退回 heuristic_context。"""
        try:
            return self.real_context(lat, lon)
        except Exception as exc:
            return self.heuristic_context(lat, lon, str(exc))


# -----------------------------------------------------------------------------
# 模組層級公開函式：server.py 主要呼叫這裡
# -----------------------------------------------------------------------------

def get_context(lat, lon):
    """給 server.py 使用的簡易入口；會自動 fallback，不會輕易丟錯到前端。"""
    return WeatherAQIClient().context(lat, lon)


def get_real_context(lat, lon):
    """測試或除錯用入口；只取真實外部 API，失敗時直接丟出錯誤。"""
    return WeatherAQIClient().real_context(lat, lon)


if __name__ == "__main__":
    # 直接執行本檔時，輸出一份 sample context JSON，方便快速驗證 API key 與資料格式。
    sample_lat = parse_float(os.getenv("NEXT_STOPS_SAMPLE_LAT"), 25.044)
    sample_lon = parse_float(os.getenv("NEXT_STOPS_SAMPLE_LON"), 121.5294)
    print(json.dumps(get_context(sample_lat, sample_lon), ensure_ascii=False, indent=2))
