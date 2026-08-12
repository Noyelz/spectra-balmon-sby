import xml.etree.ElementTree as ET

def parse_obw_xml(xml_content):
    """
    Mengekstrak Bandwidth (kHz), Channel Power (dBm), dan Frekuensi Carrier Terukur (MHz) dari file OBW .fmspa
    """
    try:
        root = ET.fromstring(xml_content)
        obw_data = root.find('.//OBW/MeasurementData')
        
        bw_khz = 0.0
        level_dbm = 0.0
        freq_mhz = 0.0
        
        if obw_data is not None:
            bw_hz = float(obw_data.get('percentBandwidth', 0))
            bw_khz = round(bw_hz / 1000.0, 2)
            
            cp = float(obw_data.get('channelPower', 0))
            level_dbm = round(cp, 2)

        # Mengambil frekuensi carrier terukur dari Marker 1 OBW
        m1_obw = root.find('.//Marker[@name="SpaMarkerMeasurement1"]//Setting[@id="MarkerPosition"]')
        if m1_obw is not None:
            freq_hz = float(m1_obw.get('value', 0))
            freq_mhz = round(freq_hz / 1_000_000.0, 2)
            
        return bw_khz, level_dbm, freq_mhz
    except Exception as e:
        print(f"ERROR PARSE OBW: {e}")
        return 0.0, 0.0, 0.0


def parse_deviasi_xml(xml_content):
    """
    Mengekstrak Peak Deviasi (kHz) dari file Deviasi .fmspa (Delta Marker M2 Δ M1)
    """
    try:
        root = ET.fromstring(xml_content)
        marker_positions = {}
        deviasi_khz = 0.0

        for marker in root.findall('.//Marker'):
            marker_name = marker.get('name', '').replace('SpaMarkerMeasurement', 'M')
            state = marker.find('.//Setting[@id="MarkerState"]')

            if state is not None and state.get('value') == '1':
                freq_setting = marker.find('.//Setting[@id="MarkerPosition"]')
                mode_setting = marker.find('.//Setting[@id="MarkerMode"]')
                ref_setting = marker.find('.//Setting[@id="MarkerReference"]')

                if freq_setting is not None:
                    freq_hz = float(freq_setting.get('value'))
                    marker_positions[marker_name] = freq_hz
                    mode = mode_setting.get('value') if mode_setting is not None else "POS"

                    if mode == "DELT":
                        ref_id = ref_setting.get('value') if ref_setting is not None else "1"
                        ref_name = f"M{ref_id}"
                        ref_freq = marker_positions.get(ref_name, 0)
                        
                        delta_freq_hz = abs(freq_hz - ref_freq)
                        deviasi_khz = round(delta_freq_hz / 1000.0, 2)

        return deviasi_khz
    except Exception as e:
        print(f"ERROR PARSE DEVIASI: {e}")
        return 0.0


def parse_harmonisa_xml(xml_content, level_dbm):
    """
    Mengekstrak Marker H1, H2, H3 (MHz & dBm) serta Menghitung Selisih Attenuasi (dB = |Level_dBm - H_dBm|)
    """
    harmonisa = {
        'h1_mhz': None, 'h1_dbm': None, 'h1_db': None,
        'h2_mhz': None, 'h2_dbm': None, 'h2_db': None,
        'h3_mhz': None, 'h3_dbm': None, 'h3_db': None
    }
    try:
        root = ET.fromstring(xml_content)
        
        for marker in root.findall('.//Marker'):
            marker_name = marker.get('name', '').replace('SpaMarkerMeasurement', 'M')
            state = marker.find('.//Setting[@id="MarkerState"]')

            if state is not None and state.get('value') == '1':
                freq_setting = marker.find('.//Setting[@id="MarkerPosition"]')
                amp_setting = marker.find('.//Setting[@id="MarkerValue"]')

                if freq_setting is not None and amp_setting is not None:
                    freq_mhz = round(float(freq_setting.get('value')) / 1_000_000.0, 1)
                    amp_dbm = round(float(amp_setting.get('value')), 2)
                    
                    # Rumus otomatis H(dB) = |Level_dBm - H_dBm|
                    amp_db = round(abs(level_dbm - amp_dbm), 2)

                    if marker_name == 'M1':
                        harmonisa['h1_mhz'] = freq_mhz
                        harmonisa['h1_dbm'] = amp_dbm
                        harmonisa['h1_db'] = amp_db
                    elif marker_name == 'M2':
                        harmonisa['h2_mhz'] = freq_mhz
                        harmonisa['h2_dbm'] = amp_dbm
                        harmonisa['h2_db'] = amp_db
                    elif marker_name == 'M3':
                        harmonisa['h3_mhz'] = freq_mhz
                        harmonisa['h3_dbm'] = amp_dbm
                        harmonisa['h3_db'] = amp_db

        return harmonisa
    except Exception as e:
        print(f"ERROR PARSE HARMONISA: {e}")
        return harmonisa
