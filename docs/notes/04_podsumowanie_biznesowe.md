# Część 3. Podsumowanie biznesowe

Co wyniki projektu znaczą dla banku i jak o nich opowiedzieć. Wszystkie liczby pochodzą z danych syntetycznych (6 miesięcy, 10 000 klientów, 257 947 transakcji).

---

## 1. Problem biznesowy

Bank (np. Revolut) musi wyłapywać oszustwa, ale **nie może blokować zwykłych klientów**. Każdy błąd kosztuje w jedną albo w drugą stronę:

| błąd | co się dzieje | koszt dla banku |
|---|---|---|
| **przepuszczony fraud** (false negative) | oszust wyprowadza pieniądze | strata pieniędzy, zwroty dla klientów, kary regulatora |
| **fałszywy alarm** (false positive) | zablokowana karta uczciwego klienta | zły klient, telefony na infolinię, czas analityka, klient odchodzi do konkurencji |

Cel projektu: **wykrywać jak najwięcej fraudu przy jak najmniejszej liczbie fałszywych alarmów**, i umieć wytłumaczyć każdą decyzję.

## 2. Skala problemu

- Fraud to tylko **1,64% transakcji**, ale aż **14,65% wartości**: 3,43 mln z 23,4 mln EUR.
- Oszuści wydają mało razy, ale dużo naraz. Średnia transakcja fraudowa to 808 EUR, a zwykła 79 EUR.
- **Wniosek:** liczenie samych transakcji zaniża problem, więc trzeba patrzeć też na kwoty.

## 3. Gdzie jest ryzyko

| obszar | fraud rate | dla porównania |
|---|---|---|
| transakcje za granicą | 10,14% | w kraju klienta 0,11% |
| sprzedawcy spoza Europy (np. CN) | do 42,59% | Europa poniżej 1,2% |
| crypto | 18,97% | zakupy online 1,23% |
| elektronika | 10,21% | |
| karty podarunkowe | 8,40% | |
| godzina 3:00 w nocy | najwyższy w ciągu doby | |
| plan konta (standard/premium/metal) | 1,38–1,97% | prawie bez różnicy |

**Wniosek:** ryzyko zależy od **zachowania** (gdzie, w czym, z jakiego urządzenia, jak szybko), a nie od tego, kim jest klient (plan konta prawie nic nie mówi).

## 4. Najmocniejsze sygnały oszustwa

| sygnał | fraud rate, gdy się zapali | lift |
|---|---|---|
| 5+ transakcji w 10 minut | 100%* | ×60,8 |
| nowe urządzenie (pierwsze 24 h) | 43,45% | ×26,4 |
| ryzykowna kategoria | 11,59% | ×7,0 |
| kwota > 3× średnia klienta | 9,55% | ×5,8 |
| nowy kraj | 8,01% | ×4,9 |
| historia fraud/chargeback | 5,41% | ×3,3 |
| nocna godzina | 3,04% | ×1,9 |

\* Efekt danych syntetycznych, opisany w ograniczeniach.

**Wniosek:** najgroźniejszy wzorzec to **przejęcie konta**: nowe urządzenie, nowy kraj, ryzykowna kategoria i duża kwota naraz.

## 5. Co dał scoring

**Prosta metoda** (alarm przy każdej kwocie powyżej 191,57 EUR): 22 276 alarmów, z czego tylko **14,8%** to fraud. Na jednego oszusta przypada 6 zablokowanych uczciwych klientów, więc to nie do przyjęcia.

**Scoring v1** (wagi z planu, próg 60): precision 64,3%, ale analiza pokazała, że reguła „historia klienta” odpowiada za 96% fałszywych alarmów.

**Scoring v2** (poprawione wagi, próg 60):

| | v1 | v2 | zmiana |
|---|---|---|---|
| fałszywe alarmy | 1 009 | **227** | **−78%** |
| wykryte fraudy | 1 821 | 1 742 | −4% |
| precision | 64,3% | **88,5%** | +24 pkt proc. |

**Wniosek:** jedna zmiana oparta na danych (mniej wagi dla starej historii, więcej dla nowego urządzenia) usunęła **prawie 4 na 5 fałszywych alarmów** kosztem kilku procent wykrytych fraudów.

## 6. Rekomendacja: jak bank mógłby tego użyć

Zamiast jednego progu, **dwa poziomy reakcji** (scoring v2):

| wynik | co robić | ile transakcji w 6 mies. | ile to fraud |
|---|---|---|---|
| **80+ (CRITICAL)** | automatyczna blokada i SMS do klienta | 466 | 99,1% |
| **50–79** | kolejka do analityka (sprawdzenie ręczne) | 3 820 (ok. 21 dziennie) | ok. 62% |
| poniżej 50 | przepuszczamy, ewentualnie monitoring | reszta | niski |

Efekt:
- Automatyczne blokady prawie nigdy nie trafiają w niewinnych (4 pomyłki na pół roku).
- Analityk dostaje ok. 21 spraw dziennie, z czego większość to prawdziwe oszustwa.
- Łącznie łapiemy **2 834 fraudy (66,8%)**, czyli o ponad 1 000 więcej niż v1 przy progu 60.

Próg to **decyzja biznesowa**, nie techniczna. Zależy od tego, ilu analityków ma bank i ile kosztuje mu przepuszczony fraud w porównaniu z wkurzonym klientem.

## 7. Czego scoring nie łapie

- Przy progu 50 ok. **1 400 fraudów (33%) przechodzi niezauważonych**. To głównie oszustwa, które wyglądają jak normalne zakupy: zwykła kwota, znane urządzenie, kraj klienta.
- Kolejne kroki w prawdziwym projekcie:
  - dodać sygnały, np. zmianę hasła lub numeru telefonu przed płatnością, nowego odbiorcę przelewu, prędkość „podróży” między krajami;
  - przetestować model ML (np. regresję logistyczną albo drzewa decyzyjne) i porównać go ze scoringiem;
  - sprawdzić wagi na nowym okresie (np. lipiec–grudzień).

## 8. Ograniczenia (uczciwie)

- Dane są **syntetyczne**. Etykieta `is_fraud` jest pełna i pewna, a w banku byłaby opóźniona i niekompletna.
- Sygnał „5+ transakcji w 10 min” ma 100%, a 5 kategorii ma 0% fraudu. To efekt generatora, w rzeczywistości byłoby inaczej.
- Wagi v2 dobrano na tych samych danych, na których je oceniamy. W banku sprawdzono by je na nowym, niewidzianym okresie.
- Okno 30 dni i progi poziomów (30/60/80) to **założenia demonstracyjne**.
- Scoring jest **regułowy i przejrzysty**, ale nie jest modelem produkcyjnym.

---

## Wersja na rozmowę (ok. 1 minuta)

> „Zbudowałem w PostgreSQL i Pythonie analizę fraudu na 258 tys. transakcji. Fraud to 1,6% transakcji, ale prawie 15% wartości, i koncentruje się w transakcjach zagranicznych, crypto i elektronice. Najpierw sprawdziłem najprostsze podejście, czyli oznaczanie wysokich kwot: łapało dużo, ale 85% alarmów było fałszywych. Zbudowałem więc przejrzysty scoring z 7 sygnałów zachowania, opartych na funkcjach okna w SQL. Analiza fałszywych alarmów pokazała, że jedna reguła, historia klienta, odpowiada za 96% z nich. Po zmianie wag fałszywe alarmy spadły o 78%, a precyzja wzrosła z 64% do 88%, przy prawie tej samej liczbie wykrytych fraudów. Zaproponowałem też dwa progi reakcji: automatyczna blokada od 80 punktów i kolejka do analityka od 50.”
