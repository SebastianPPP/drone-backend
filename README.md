# Dokumentacja techniczna systemu kontroli roju dronów

## Spis treści
1. Wstęp
2. Architektura systemu
3. Szczegółowy opis komponentów
    1. Backend w pliku app.py
    2. Logika frontend w pliku script.js
    3. Interfejs użytkownika w pliku index.html
4. Instrukcja użytkownika

---

## Wstęp
System GCS (Ground Control Station) w wersji 2.0 to zaawansowana platforma webowa służąca do zarządzania rojem bezzałogowych statków powietrznych. Projekt ten ewoluował z prostej architektury REST API do wydajnego systemu opartego na gniazdach sieciowych (WebSockets). Nowa wersja eliminuje opóźnienia w telemetrii i wprowadza kluczowe zabezpieczenia wymagane w środowiskach produkcyjnych.

## Architektura systemu
System działa w modelu klient-serwer z wykorzystaniem dwukierunkowej komunikacji asynchronicznej.
* **Drony** to autonomiczne jednostki wysyłające telemetrię i odbierające misje.
* **Serwer backend** pełni rolę huba komunikacyjnego, który autoryzuje urządzenia i dystrybuuje dane.
* **Klient frontend** to panel operatora wizualizujący stan roju na mapie i wirtualnym kokpicie (HUD).

---

## Szczegółowy opis komponentów

### 1. Backend w pliku app.py

**Opis**
Zmodernizowany rdzeń serwera backendowego został przekształcony z architektury REST API na system czasu rzeczywistego. Aplikacja wykorzystuje bibliotekę Flask-SocketIO i pełni rolę asynchronicznego huba komunikacyjnego. Główną zmianą jest wprowadzenie dwukierunkowej transmisji danych między rojem dronów a stacją kontroli, co pozwala na natychmiastową reakcję systemu.

**Rozwiązane problemy i ulepszenia**
* **Bezpieczeństwo i zmienne środowiskowe**
  Wrażliwe dane, takie jak login, hasło czy klucze API, zostały usunięte z kodu źródłowego. Przeniesiono je do konfiguracji w pliku .env, co eliminuje ryzyko wycieku poufnych informacji.
* **Autoryzacja dronów poprzez tokeny**
  Wdrożono weryfikację nagłówków X-Drone-Token. Tylko urządzenia posiadające unikalny klucz kryptograficzny mogą przesyłać telemetrię. Zabezpiecza to system przed podszywaniem się pod drony.
* **Asynchroniczny zapis danych**
  Proces zapisu stanu systemu do pliku drones_state.json został przeniesiony do osobnego wątku w tle. Operacje dyskowe nie blokują już głównej pętli komunikacyjnej, co zapewnia płynność działania nawet przy dużym obciążeniu.

**Stos technologiczny**
* Język to Python 3.10+
* Framework to Flask w połączeniu z Flask-SocketIO
* Współbieżność zapewnia biblioteka Eventlet
* Baza danych to słownik w pamięci RAM wspierany zapisem do pliku JSON
* Autoryzacja oparta jest na tokenach dla dronów i sesji dla operatora

---

### 2. Logika frontend w pliku script.js

**Opis**
Całkowicie przepisany silnik klienta działa w oparciu o architekturę sterowaną zdarzeniami. Skrypt odpowiada za nawiązanie stałego połączenia z serwerem i dynamiczną aktualizację modelu strony (DOM).

**Rozwiązane problemy i ulepszenia**
* **Komunikacja w czasie rzeczywistym**
  Zastąpiono mechanizm cyklicznego odpytywania serwera subskrypcją zdarzeń socket.on. Dane telemetryczne trafiają na mapę i HUD w momencie ich otrzymania przez serwer, co redukuje opóźnienia do minimum.
* **Stabilizacja interfejsu**
  Wprowadzono inteligentne zarządzanie listą dronów. Skrypt aktualizuje tylko te elementy listy, które uległy zmianie. Eliminuje to migotanie interfejsu i problemy z interakcją myszką.
* **Adapter współrzędnych**
  Zaimplementowano funkcje normalizujące koordynaty między różnymi standardami bibliotek mapowych i geometrycznych. Zapobiega to błędom logicznym przy generowaniu tras.
* **Centrowanie kamery**
  Dodano funkcję płynnego podążania kamery za wybranym dronem.

**Stos technologiczny**
* Język to JavaScript w standardzie ES6+
* Komunikacja odbywa się przez Socket.IO Client
* Mapy obsługuje biblioteka Leaflet.js
* Obliczenia geometryczne wykonuje Turf.js

---

### 3. Interfejs użytkownika w pliku index.html

**Opis**
Nowoczesny interfejs użytkownika został zaprojektowany zgodnie z paradygmatem offline-first. Panel umożliwia zarządzanie misjami oraz monitorowanie parametrów lotu na wirtualnym kokpicie.

**Rozwiązane problemy i ulepszenia**
* **Tryb offline**
  System został uniezależniony od zewnętrznych serwerów treści. Wszystkie biblioteki są ładowane lokalnie, co umożliwia pracę w terenie bez dostępu do internetu.
* **Responsywność**
  Dzięki zastosowaniu elastycznych kontenerów i zapytań o media, interfejs skaluje się poprawnie na urządzeniach mobilnych, dostosowując układ paska bocznego i wskaźników.
* **Optymalizacja wydajności HUD**
  Animacje instrumentów lotniczych wykorzystują akcelerację sprzętową karty graficznej. Eliminuje to przycięcia przeglądarki przy wysokiej częstotliwości odświeżania danych.
* **Poprawa wrażeń użytkownika**
  Zastosowano animację obramowania dla listy dronów, co eliminuje drgania elementów przy najeżdżaniu kursorem.

**Stos technologiczny**
* Struktura oparta na HTML5 i szablonach Jinja2
* Style wykorzystują CSS3 ze zmiennymi i animacjami
* Komponenty to kontenery mapy, ikony SVG i wskaźniki CSS

---

## Instrukcja użytkownika

### 1. Wymagania wstępne
Upewnij się, że posiadasz zainstalowane środowisko Python w wersji 3.10 lub nowszej oraz menedżer pakietów pip.

### 2. Instalacja zależności
W katalogu głównym projektu uruchom instalację wymaganych bibliotek.
```bash
pip install flask flask-socketio eventlet python-dotenv
```

### 3. Konfiguracja bezpieczeństwa (Render.com)
Aplikacja jest przystosowana do pracy w chmurze (Cloud Native). Ze względów bezpieczeństwa poświadczenia nie są przechowywane w pliku, lecz w zmiennych środowiskowych serwera.

1. W panelu administracyjnym Render.com przejdź do zakładki **Environment**.
2. Zdefiniuj następujące zmienne:

| Klucz (Key) | Opis | Przykład |
| :--- | :--- | :--- |
| `ADMIN_USER` | Login operatora GCS | `admin` |
| `ADMIN_PASS` | Hasło operatora GCS | `SilneHaslo123!` |
| `DRONE_API_KEY` | Token autoryzacyjny dla dronów | `KluczRoju_XYZ` |
| `SECRET_KEY` | Klucz szyfrowania sesji Flask | `losowy_ciag_znakow` |

### 4. Uruchomienie serwera
W środowisku produkcyjnym (Render) serwer uruchamia się automatycznie po wykryciu zmian w repozytorium (Push to Deploy).
Adres publiczny API: `[wstaw swój adres]`

### 5. Podłączanie drona
Dron musi wysyłać nagłówek `X-Drone-Token` zgodny z tym ustawionym w panelu Render. Należy używać adresu HTTPS.

```python
import requests
import os

RENDER_URL = "Adres serwera na render"

# Klucz musi być taki sam jak w Environment Variables na Renderze
headers = {"X-Drone-Token": "KluczRoju_XYZ"} 

payload = {
    "drone_id": "skimmer1",
    "lat": 52.2297, "lon": 21.0122,
    "bat": 98, "roll": 0, "pitch": 0, "yaw": 0
}

try:
    r = requests.post(RENDER_URL, json=payload, headers=headers)
    print(f"Status: {r.status_code}, Odpowiedź: {r.json()}")
except Exception as e:
    print(f"Błąd połączenia: {e}")
```
### 6. Obsługa panelu

* **Wykrywanie**
  Nowe drony pojawią się w sekcji dla wykrytych urządzeń. Kliknij przycisk z plusem, aby dodać je do listy aktywnych.

* **Śledzenie**
  Kliknij drona na liście lub mapie. Kamera automatycznie wycentruje się na nim, a wirtualny kokpit pokaże jego parametry.

* **Misja**
  Kliknij przycisk nowej misji i wybierz typ obszarowy. Zaznacz teren na mapie, a następnie wgraj misję do drona.

* **Awaryjne przerwanie**
  Użyj przycisku stop lub usuń misję, aby natychmiast anulować zadania i przełączyć drony w tryb powrotu lub zawisu.