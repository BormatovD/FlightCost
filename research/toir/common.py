"""Общие справочники для fe.py и final.py."""
# Чартерные, грузо-пассажирские и единичные перевозчики: другой профиль налёта и ТОиР, мало бортов
CHARTER = {"WO (1)", "X9", "8C", "RD", "NA", "U5", "GL", "09Q", "0JQ", "1BQ", "2HQ", "GCA", "N8", "5Y", "WL", "TZ", "MX", "XP", "3M"}
CLASS = {**dict.fromkeys("A19N A20N A21N A318 A319 A320 A321 B712 B733 B734 B735 B737 B738 B739 B38M B39M B752 B753 MD80 MD90 BCS1 BCS3".split(), "узкофюзеляжные"),
         **dict.fromkeys("A306 A332 A333 A339 A359 B744 B748 B762 B763 B764 B772 B77W B788 B789 B78X MD11 DC10".split(), "широкофюзеляжные"),
         **dict.fromkeys("CRJ1 CRJ2 CRJ7 CRJ9 E135 E145 E170 E75L E190 E195 DH8D AT76 AT45 SF34 E120 DH8A DH8B DH8C".split(), "региональные")}
