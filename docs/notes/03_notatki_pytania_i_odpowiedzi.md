# Notatki: pytania i odpowiedzi z projektu

Zebrane wyjaśnienia z rozmów, w kolejności zadawania pytań.

---

## 1. Czy `is_fraud` mówi na 100%, że to oszustwo?

- **W naszych danych tak**, bo sami wygenerowaliśmy te 4 242 oszustwa (skrypt 05).
- `is_fraud` to **„klucz odpowiedzi”**, a nie wynik analizy. Scoring go nie widzi. Patrzy tylko na zachowanie (kwota, urządzenie, kraj, godzina).
- **W prawdziwym banku** etykieta pojawia się po tygodniach (zgłoszenie klienta, chargeback, dochodzenie) i nigdy nie jest pełna: część oszustw nikt nie zgłosi, a czasem klient kłamie (*friendly fraud*).
- **Do README:** „`is_fraud` w danych syntetycznych to pełna i pewna etykieta, a w rzeczywistości byłaby opóźniona i niekompletna”.

## 2. „Używamy `is_fraud` tylko do oceny scoringu, nigdy do jego liczenia”: co to znaczy?

Przykład z życia:
- **1 marca, 14:05:** płatność 1 500 EUR. Bank nie wie, czy to fraud.
- **20 marca:** klient zgłasza „to nie ja”.
- **10 kwietnia:** bank potwierdza fraud i dopiero wtedy `is_fraud = true`.

Scoring musi zadziałać 1 marca o 14:05, więc może korzystać tylko z tego, co wtedy wiadomo. `is_fraud` używamy dopiero po fakcie, żeby sprawdzić, jak dobrze scoring zgadywał (`04_false_positives.sql`).

**Analogia:** scoring to uczeń, `is_fraud` to klucz odpowiedzi do testu. Zajrzenie do klucza to błąd zwany **data leakage** (wyciek danych). Rekruterzy często o to pytają.

## 3. Kolumny ryzyka klienta (`fact_customer_risk`)

- **`previous_fraud`:** czy na koncie był potwierdzony fraud w latach 2020–2025, przed okresem analizy. Zwykle klient był **ofiarą**, a nie oszustem. Ma to 285 klientów.
- **`chargebacks`:** ile razy w 2025 klient reklamował płatność w banku. Co najmniej jeden ma 807 klientów.
- Obie kolumny to **historia znana w chwili płatności**, więc wolno ich używać w scoringu. Razem tworzą sygnał `s_fraud_history`.
- **`risk_score` / `risk_score_v2`:** wynik klienta na 30.06.2026, czyli **najwyższy** wynik jego transakcji z ostatnich 30 dni. Maksimum, bo wystarczy jedna bardzo podejrzana transakcja; średnia by ją rozmyła.
- **`risk_level` / `risk_level_v2`:** ten sam wynik jako etykieta. Kolumny bez `_v2` to v1 (plan), z `_v2` to v2 (poprawione wagi).

## 4. Dlaczego wynik klienta liczymy tylko z ostatnich 30 dni?

Bo pytamy: **„czy klient jest ryzykowny teraz?”**, a nie „czy kiedykolwiek był”.
1. Stare alarmy bank już załatwił.
2. Lista do sprawdzenia nie może puchnąć, bo analitycy mają ograniczony czas.
3. Ryzyko się zmienia: po podróży klient wraca do normalnych zakupów.

To **okno kroczące** (*rolling window*). 30 dni to nasze **założenie**, mniej więcej jeden cykl rozliczeniowy karty. Zmienia się je w `05_risk_score_v2.sql` w linii `INTERVAL '30 days'`.

## 5. Jaki okres analizujemy?

- Transakcje: **1.01–30.06.2026** (257 947).
- Wcześniejsze lata występują tylko jako tło: data założenia konta (od 2020) oraz `previous_fraud` i `chargebacks`.
- 6 miesięcy, bo plan mówi o 100–300 tys. transakcji. To wystarcza do trendu miesięcznego, a działa szybko na laptopie.

## 6. Dlaczego VS Code się zawiesza przy `SELECT *`?

`SELECT * FROM fact_transaction_risk` to ponad 4 mln komórek, a wtyczka próbuje je narysować naraz.
- Do podglądu dużych tabel: `LIMIT 100` (w T-SQL: `SELECT TOP 100`).
- Do analizy używaj `COUNT`, `GROUP BY` i agregatów.
- Małe tabele (`dim_merchant`, `dim_customer`) można wyświetlać całe.

## 7. `risk_level` vs `risk_level_v2`

- Te same progi: 0–29 LOW, 30–59 MEDIUM, 60–79 HIGH, 80+ CRITICAL.
- `risk_level` wynika z `risk_score` (v1), a `risk_level_v2` z `risk_score_v2` (v2).
- Różnią się tylko u klientów z historią fraud/chargeback (v2 niżej) albo z nowym urządzeniem (v2 wyżej).
- Zmiany klientów v1 → v2: MEDIUM → LOW 446, HIGH → MEDIUM 113, CRITICAL → HIGH 33. W górę poszło tylko 17 klientów.

## 8. Po co zmieniliśmy wagi (v2)? Czy po to, żeby było mniej CRITICAL?

**Nie.** Celem było **mniej fałszywych alarmów przy prawie tej samej liczbie wykrytych fraudów**. Mniej CRITICAL to skutek uboczny.

Wyniki przy progu 60:

| | v1 | v2 |
|---|---|---|
| alarmy | 2 830 | 1 969 |
| prawdziwe fraudy | 1 821 | 1 742 |
| fałszywe alarmy | 1 009 | 227 |

Na poziomie CRITICAL trafność wzrosła z 90,4% do 99,1%.

Fałszywy alarm kosztuje: zablokowana karta przy kasie, zły klient i czas analityka. Bonus: v2 pozwala obniżyć próg do 50 i złapać 2 834 fraudy (ponad 1 000 więcej niż v1 przy 60) przy podobnym koszcie.

## 9. Która kolumna decydowała o fałszywych alarmach?

**`s_fraud_history`** (historia fraud/chargeback, w v1 warta +30): była w 967 z 1 009 fałszywych alarmów v1 (95,8%). W v2 takich alarmów zostało 136.

W v2 procenty wydają się wyższe, bo liczymy je od mniejszej bazy (227 alarmów), więc porównuj **liczby**. „Nowe urządzenie” w v2 daje trochę więcej fałszywych alarmów (153 zamiast 104). To świadomy koszt, bo ten sygnał łapie najwięcej przejęć kont. Szczegóły zapytania są w `falszywe_alarmy_v1_v2_linia_po_linii.md`.

## 10. Dlaczego sygnał „5+ transakcji w 10 minut” ma 100%?

Bo **tak wygenerowaliśmy dane**: szybkie serie transakcji tworzył tylko scenariusz oszustwa (card testing, przejęcie konta). Zwykli klienci w naszych danych nigdy tak nie płacili.

**Analogia:** jeśli w scenariuszu tylko złodzieje biegają po korytarzu, to „kto biega, ten złodziej” daje 100% racji, ale to efekt scenariusza, nie prawda o świecie.

W prawdziwym banku legalne serie są codziennie (metro, galeria, automaty), więc sygnał byłby mocny, ale nie idealny. Podobnie 5 kategorii ma 0% fraudu (grocery, restaurants, transport, travel, cash_withdrawal).

**Decyzja: opcja A**, czyli zostawiamy dane i opisujemy to w README.
> Sygnał „5+ transakcji w 10 minut” ma w projekcie 100% trafności, bo generator danych tworzył szybkie serie transakcji wyłącznie w scenariuszach oszustw. W prawdziwych danych legalne serie (np. transport publiczny) obniżyłyby tę wartość. Podobnie 5 kategorii merchantów ma 0% fraudu, co w rzeczywistości byłoby mało prawdopodobne.

## 11. Do czego służy `09_anomaly_detection.py`?

**Pliki 03 i 05 budują scoring. Skrypt 09 go sprawdza i porównuje z prostszymi metodami, a potem przygotowuje dane do Power BI.** Sam niczego nowego nie wykrywa.

**Analogia czujnika dymu:** zbudowaliśmy czujnik (scoring). Skrypt 09 to stanowisko testowe, na którym porównujemy go z dwoma prostymi czujnikami:
- **IQR** (alarm przy każdej kwocie powyżej 191,57 EUR) piszczy bez przerwy: łapie 77,8% fraudów, ale tylko 14,8% alarmów jest trafnych. Nie łapie card testingu, bo to drobne kwoty.
- **z-score** (kwota dziwna dla tego klienta) prawie nie piszczy: tylko 12,8% fraudów, bo duże oszustwo samo podbija średnią klienta.
- **Nasz scoring v2 ≥ 60:** 88,5% alarmów to prawdziwe fraudy, czyli 6× precyzyjniej niż IQR.

Pojęcia:
- **Recall:** ile ze wszystkich fraudów złapaliśmy.
- **Precision:** ile alarmów to prawdziwe fraudy.
- **Lift:** ile razy częściej jest fraud, gdy sygnał się zapali. Przykład: nowe urządzenie 43,45% wobec średnio 1,64%, czyli lift 26,4.
- **Korelacja** (0–1): jak bardzo wynik „idzie w parze” z fraudem. v1 ma 0,403, v2 ma 0,492.

Plan tego wymaga (sekcja 11), a porównanie to **baseline**. Odpowiada na pytanie „czemu nie wystarczy oznaczać dużych kwot?”.

**Na rozmowę:** „Najpierw sprawdziłem najprostsze podejście, czyli oznaczanie wysokich kwot. Łapało dużo fraudów, ale 85% alarmów było fałszywych. Dlatego zbudowałem scoring łączący kilka sygnałów zachowania i podniosłem trafność alarmów do 88,5%”.

## 12. Gdzie jest scoring?

- **Liczą go** pliki `03_risk_scoring.sql` (v1) i `05_risk_score_v2.sql` (v2).
- **Wyniki w bazie:** `fact_transaction_risk` (każda transakcja) i `fact_customer_risk` (każdy klient).
- **Kopia pod Power BI:** `powerbi_data\transactions_scored.csv` i `customers_risk.csv`.

## 13. Jak zbudowany jest scoring v2?

To **lista 7 pytań z punktami**: za każde „tak” system dodaje punkty i na koniec sumuje.

| pytanie | kolumna | v1 | v2 |
|---|---|---|---|
| Kwota ponad 3× wyższa niż dotychczasowa średnia klienta? | `s_amount_3x_avg` | 20 | 20 |
| Nowe urządzenie (pierwsze 24 h)? | `s_new_device` | 15 | **25** |
| Pierwsza transakcja klienta w tym kraju? | `s_new_country` | 20 | 20 |
| 5+ transakcji w 10 minut? | `s_5_tx_in_10_min` | 15 | 15 |
| Crypto, karty podarunkowe, elektronika? | `s_risky_category` | 10 | 10 |
| Wcześniejszy fraud lub chargeback? | `s_fraud_history` | 30 | **15** |
| Godzina 0:00–4:59? | `s_night_hour` | 10 | 10 |

Kroki:
1. Sygnały liczy plik 03 (funkcje okna + CASE).
2. Sumę punktów liczy plik 05 (`CASE WHEN sygnał THEN punkty ELSE 0 END` + `...`).
3. Poziom: 0–29 LOW, 30–59 MEDIUM, 60–79 HIGH, 80+ CRITICAL.
4. Wynik klienta to maksimum z ostatnich 30 dni.

**Przykład:** przejęcie konta, 2:30 w nocy, 1 500 EUR za elektronikę w Chinach z nowego telefonu daje 20 + 25 + 20 + 10 + 10 = **85, czyli CRITICAL**. Zwykłe zakupy w Biedronce w południe dają **0, czyli LOW**.

---

## 14. Skąd się biorą progi 30/50/60/70/80?

**Próg** to minimalny `risk_score`, od którego system podnosi alarm (`risk_score >= próg`). Jak poprzeczka na skoczni: kto ją przeskoczy, trafia do sprawdzenia.

- **30, 50, 70**: z planu projektu (sekcja 13: „przetestuj kilka progów ryzyka”).
- **60 i 80**: dodane, bo to granice poziomów HIGH i CRITICAL; 30 to granica MEDIUM.
- W SQL są wpisane ręcznie w `FROM (VALUES (30), (50), (60), (70), (80)) AS th(threshold)`. Możesz dopisać dowolną wartość, np. `(40)`.
- `CROSS JOIN` sprawdza każdą transakcję przy każdym progu, więc dostajemy jedną tabelę porównawczą.
- To **wartości demonstracyjne**. Ostateczny próg wybiera biznes: ilu ma analityków i co jest droższe, przepuszczony fraud czy zablokowany uczciwy klient.

## 15. Co mówi tabela progów (v1)?

**Nie ma idealnego progu, zawsze coś za coś.** Analogia: bramka na lotnisku. Za czuła piszczy przy pasku, za słaba przepuści nóż.

| próg | wykryte fraudy (recall) | trafne alarmy (precision) | fałszywe alarmy | niewinnych na 1 oszusta |
|---|---|---|---|---|
| 30 | 86,6% | 9,8% | 33 958 | 9,2 |
| 50 | 53,6% | 34,5% | 4 307 | 1,9 |
| 60 | 42,9% | 64,3% | 1 009 | 0,6 |
| 70 | 23,7% | 86,1% | 162 | 0,2 |
| 80 | 14,6% | 90,4% | 66 | 0,1 |

- Niższy próg łapie więcej oszustów, ale blokuje więcej uczciwych klientów. Przy 30 blokujemy 13,38% wszystkich uczciwych transakcji (`false_positive_rate_pct`).
- Wyższy próg prawie się nie myli, ale przepuszcza większość fraudu.
- Wniosek: wysoki próg służy do automatycznej blokady, a średni do kolejki dla analityka. Stąd dwa poziomy reakcji w podsumowaniu biznesowym.
- W v2 przy progu 60 fałszywych alarmów jest 227 zamiast 1 009.

## 16. Co to jest recall (a co precision)?

- **recall** (wykrywalność) to jaki procent **wszystkich prawdziwych fraudów** złapaliśmy: `fraud_detected / (fraud_detected + fraud_missed) × 100`. Próg 60: 1 821 / 4 242 = 42,9%.
- **precision** (trafność alarmów) to jaki procent **alarmów** to prawdziwe fraudy: `fraud_detected / flagged × 100`.
- Analogia: w stawie jest 100 szczupaków. Recall mówi, ile z nich wyłowiłeś. Precision mówi, ile z tego, co jest w sieci, to szczupaki, a nie kalosze.
- Te miary ciągną w przeciwne strony: duża sieć (próg 30) daje recall 87% i precision 10%, a mała sieć (próg 80) daje recall 15% i precision 90%.

## 17. Sygnały w fałszywych vs prawdziwych alarmach (zapytanie 3 z 04, v1, próg 60)

Porównujemy, jak często sygnał zapalał się w **fałszywych alarmach** (1 009) i w **prawdziwych** (1 821). Liczy się porównanie dwóch procentów w jednym wierszu.

| sygnał | w fałszywych | w prawdziwych | wniosek |
|---|---|---|---|
| historia fraud/chargeback | 95,8% | 61,1% | główny winowajca fałszywych alarmów |
| ryzykowna kategoria | 83,3% | 88,2% | słabo odróżnia |
| kwota > 3× średnia | 65,5% | 59,7% | słabo odróżnia |
| nowy kraj | 52,1% | 65,1% | trochę lepiej |
| nowe urządzenie | 10,3% | 86,2% | świetnie odróżnia |
| noc | 6,7% | 2,3% | słaby |
| 5+ tx w 10 min | 0% | 53,5% | idealny (efekt danych syntetycznych) |

- Analogia: „ma czapkę” jest u złodziei i uczciwych tak samo często, więc nic nie mówi. „Ma łom” jest prawie tylko u złodziei, więc za to dajemy dużo punktów.
- Dlatego w v2: historia 30 → 15 pkt, nowe urządzenie 15 → 25 pkt. Fałszywe alarmy spadły z 1 009 do 227.

## 18. Kombinacje sygnałów w alarmach (zapytanie 4 z 04, v1, próg 60)

Każdy wiersz to zestaw sygnałów, które zapaliły się razem; `alerts` to liczba alarmów z tym zestawem, `false_alarms` to ilu było uczciwych klientów, `fraud_rate_pct` to procent prawdziwych fraudów.

- **Historia bez nowego urządzenia to prawie same pomyłki** (fraud 0–7%). Przykład: kwota 3× (20) + ryzykowna kategoria (10) + historia (30) = 60 w v1, czyli alarm. W v2 jest 20 + 10 + 15 = 45, czyli brak alarmu, i znika 445 fałszywych alarmów z jednego wiersza.
- **Kwota 3× + nowe urządzenie + nowy kraj + ryzykowna kategoria = 91,5% fraudu**: wzorzec przejęcia konta, który nie potrzebuje historii, żeby przekroczyć próg.
- Pojedynczy sygnał nic nie przesądza, liczy się kombinacja. Analogia: sam kaszel nic nie znaczy, ale kaszel + gorączka + utrata węchu to diagnoza.

## 19. Co znaczy TN (i TP, FP, FN)?

Macierz pomyłek (zapytanie 1 z 04) dzieli transakcje na 4 szufladki:

| skrót | nazwa | alarm? | naprawdę fraud? | próg 60 (v1) |
|---|---|---|---|---|
| TP | true positive | tak | tak | 1 821, złapany oszust |
| FP | false positive | tak | nie | 1 009, fałszywy alarm |
| FN | false negative | nie | tak | 2 421, przepuszczony oszust |
| TN | true negative | nie | nie | 252 696, spokojny uczciwy klient |

- Pierwsze słowo: czy system miał rację (true) czy się pomylił (false). Drugie: co powiedział (positive = alarm, negative = brak alarmu).
- `false_positive_rate_pct = FP / (FP + TN) × 100`, czyli jaki procent uczciwych transakcji dostał niepotrzebny alarm. Próg 60: 0,40%.

---

## Do README: lista ograniczeń i założeń

- Dane syntetyczne; `is_fraud` jest pełne i pewne, a w rzeczywistości byłoby opóźnione i niekompletne.
- Sygnał „5+ tx w 10 min” ma 100% trafności, a 5 kategorii ma 0% fraudu. To efekt generatora.
- Wagi v2 dobrano, patrząc na te same dane, na których je oceniamy; w banku sprawdzono by je na nowym okresie.
- Okno 30 dni dla wyniku klienta i progi poziomów (30/60/80) to założenia demonstracyjne.
- Scoring jest regułowy i nie jest modelem produkcyjnym.
