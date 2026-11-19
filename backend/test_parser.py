import pandas as pd
from parser import parse_excel_or_csv

data = {
    "idRuta": ["TAP", "No Disponible", "TAP", "TAP", "No Disponible", "No Disponible", "TAP"],
    "idVehiculo": ["Z917899", "Z917859", "Z917838", "Z917807", "Z917865", "Z917881", "Z917880"],
    "fechaHoraLecturaDato": [
        "26 oct 2026, 0:00:00",
        "26 oct 2026, 0:00:00",
        "26 oct 2026, 0:00:00",
        "26 oct 2026, 0:00:00",
        "26 oct 2026, 0:00:00",
        "26 oct 2026, 0:00:00",
        "26 oct 2026, 0:00:00"
    ],
    "fechaHoraEnvioDato": [
        "26 oct 2026, 0:00:00",
        "26 oct 2026, 0:00:00",
        "26 oct 2026, 4:10:13",
        "26 oct 2026, 0:00:00",
        "26 oct 2026, 0:00:00",
        "26 oct 2026, 0:00:00",
        "26 oct 2026, 0:00:00"
    ],
    "Coordenadas": [
        "4.467547,-74.127411",
        "4.467464,-74.127319",
        "4.467269,-74.127069",
        "4.467864,-74.127269",
        "4.530533,-74.119692",
        "4.467853,-74.127108",
        "4.467094,-74.128217"
    ],
    "tipoBus": ["P", "P", "P", "P", "P", "P", "P"],
    "RangoLatencia": [None, None, "5) Mayor a 30 Min", None, None, None, None],
    "tramaRetransmitida": [False, False, True, False, False, False, False],
    "velocidadVehiculo": [0, 0, 0, 0, 0, 0, 0],
    "aceleracionVehiculo": [0, 0, 0, 0, 0, 0, 0]
}

df = pd.DataFrame(data)
test_file = "sample_test.xlsx"
df.to_excel(test_file, index=False)
print("Saved sample_test.xlsx")

parsed = parse_excel_or_csv(test_file, test_file)
print(f"Parsed {len(parsed)} rows successfully:")
for r in parsed:
    print(f"Bus: {r['idVehiculo']}, Falla: {r['tramaRetransmitida']}, Latencia: {r['latenciaMinutos']} min, Coords: ({r['latitud']}, {r['longitud']}), Rango: {r['RangoLatencia']}")
