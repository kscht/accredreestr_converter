// ВНИМАНИЕ: следующая команда удаляет все узлы и связи в активной базе Neo4j.
MATCH (n) DETACH DELETE n;

// Generated from JSONL by cypher_convert.export_cypher
// Labels match specs/kg/mapping.json node_kinds.kind
// Each certificate block ends with ';' for multi-statement clients (Neo4j Browser).

// --- certificate line 1 ---
MERGE (c:Certificate {uri: 'urn:accred:v1:Certificate:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba'})
SET c.ControlOrgan = 'Министерство образования Свердловской области'
SET c.EduOrgFullName = 'государственное бюджетное образовательное учреждение начального профессионального образования Свердловской области "Нижнесалдинское профессиональное училище"'
SET c.EduOrgINN = '6622002460'
SET c.EduOrgKPP = '662201001'
SET c.EduOrgOGRN = '1026600786783'
SET c.EduOrgShortName = 'ГБОУ НПО СО "НСПУ"'
SET c.EndDate = '2015-03-30'
SET c.IsFederal = false
SET c.IssueDate = '2010-03-30'
SET c.PostAddress = '624741 г.Нижняя Салда, ул.Парижской Коммуны, 1'
SET c.RegNumber = '5087'
SET c.RegionCode = '66'
SET c.RegionName = 'Свердловская область'
SET c.StatusName = 'Недействующее'
MERGE (s0:Supplement {uri: 'urn:accred:v1:Supplement:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:788302'})
SET s0.EduOrgAddress = '624741 г.Нижняя Салда, ул.Парижской Коммуны, 1'
SET s0.EduOrgFullName = 'государственное бюджетное образовательное учреждение начального профессионального образования Свердловской области "Нижнесалдинское профессиональное училище"'
SET s0.EduOrgKPP = '662201001'
SET s0.EduOrgShortName = 'ГБОУ НПО СО "НСПУ"'
SET s0.IssueDate = '2012-06-26'
SET s0.Number = '2'
SET s0.StatusName = 'Недействующее'
MERGE (c)-[:HAS_SUPPLEMENT]->(s0)
MERGE (p_si0_0:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:788302:0:28011b5a-99eb-e660-8e06-ed87def995e0'})
SET p_si0_0.ProgrammCode = '230103.02'
SET p_si0_0.ProgrammName = 'Мастер по обработке цифровой информации'
MERGE (s0)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si0_0)
MERGE (elv0:EducationalLevel {uri: 'urn:accred:v1:EducationalLevel:2fa74e30586c8547db0264ba7b8d98f661bff110809b4a17c051ab6ef1a61e0d'})
SET elv0.name = 'Среднее профессиональное образование'
MERGE (p_si0_0)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si0_1:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:788302:1:b237326b-2512-81d5-242c-f6330a6f70a7'})
MERGE (s0)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si0_1)
MERGE (elv1:EducationalLevel {uri: 'urn:accred:v1:EducationalLevel:0165aaa5c30d3405b9a74c45c02a7c769f827fd48227377318dc437d21fc61ca'})
SET elv1.name = 'Начальное профессиональное образование'
MERGE (p_si0_1)-[:HAS_EDUCATION_LEVEL]->(elv1)
MERGE (p_si0_2:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:788302:2:b1a5a6c5-000f-ad1d-1877-5f870257373d'})
SET p_si0_2.UGSCode = '230000'
SET p_si0_2.UGSName = 'Информатика и вычислительная техника'
MERGE (s0)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si0_2)
MERGE (p_si0_2)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (a_si0:ActualEducationOrganization {uri: 'urn:accred:v1:AEO:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:supplement:77733933-0fe3-d64b-b4bb-ce2c9a66f4ab'})
SET a_si0.Email = 'nspu@bk.ru'
SET a_si0.Fax = '34345-33606'
SET a_si0.FullName = 'государственное бюджетное образовательное учреждение начального профессионального образования Свердловской области "Нижнесалдинское профессиональное училище"'
SET a_si0.HeadName = 'Хрулькова Надежда Ивановна'
SET a_si0.HeadPost = 'Директор'
SET a_si0.INN = '6622002460'
SET a_si0.KPP = '662201001'
SET a_si0.OGRN = '1026600786783'
SET a_si0.Phone = '34345-33606'
SET a_si0.PostAddress = '624610 г.Нижняя Салда, ул.Парижской Коммуны, 1, 2'
SET a_si0.RegionName = 'Свердловская область'
SET a_si0.ShortName = 'ГБОУ НПО СО "НСПУ"'
MERGE (s0)-[:HAS_ACTUAL_EDUCATION_ORGANIZATION]->(a_si0)
MERGE (a_si0)-[:OFFERS_EDUCATION_LEVEL]->(elv1)
MERGE (a_si0)-[:OFFERS_EDUCATION_LEVEL]->(elv0)
MERGE (s1:Supplement {uri: 'urn:accred:v1:Supplement:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817'})
SET s1.EduOrgAddress = '624741 г.Нижняя Салда, ул.Парижской Коммуны, 1'
SET s1.EduOrgFullName = 'государственное бюджетное образовательное учреждение начального профессионального образования Свердловской области "Нижнесалдинское профессиональное училище"'
SET s1.EduOrgKPP = '662201001'
SET s1.EduOrgShortName = 'ГБОУ НПО СО "НСПУ"'
SET s1.IssueDate = '2010-03-30'
SET s1.Number = '1'
SET s1.StatusName = 'Недействующее'
MERGE (c)-[:HAS_SUPPLEMENT]->(s1)
MERGE (p_si1_0:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:0:ee513b05-337b-4781-bfcc-5125edadb00a'})
SET p_si1_0.UGSCode = '110000'
SET p_si1_0.UGSName = 'Сельское и рыбное хозяйство'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_0)
MERGE (p_si1_0)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_1:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:1:4808f8bd-08db-c6e9-f4bb-0439780926a8'})
SET p_si1_1.ProgrammCode = '19861'
SET p_si1_1.ProgrammName = 'Электромонтер по ремонту и обслуживанию электрооборудования'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_1)
MERGE (p_si1_1)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_2:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:2:5d46b5a7-7d03-10fb-ee72-1b27f50e0292'})
SET p_si1_2.ProgrammCode = '34.2'
SET p_si1_2.ProgrammName = 'Повар, кондитер'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_2)
MERGE (p_si1_2)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_3:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:3:730d2e17-e2ee-9610-ede3-674699970b9a'})
SET p_si1_3.ProgrammCode = '11620'
SET p_si1_3.ProgrammName = 'Газосварщик'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_3)
MERGE (p_si1_3)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_4:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:4:e2fa55d4-5b88-581d-c476-2dac39020a9f'})
SET p_si1_4.UGSCode = '38.00.00'
SET p_si1_4.UGSName = 'Экономика и управление'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_4)
MERGE (p_si1_4)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_5:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:5:e67f450b-7686-eba7-b59b-b3824b65b13b'})
SET p_si1_5.ProgrammCode = '16199'
SET p_si1_5.ProgrammName = 'Оператор электронно-вычислительных машин'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_5)
MERGE (p_si1_5)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_6:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:6:efe5995e-1178-724e-8c41-65ad378c58c9'})
SET p_si1_6.ProgrammCode = '34.3'
SET p_si1_6.ProgrammName = 'Продавец, контролер-кассир'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_6)
MERGE (p_si1_6)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_7:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:7:f689e3fd-b23d-5ba6-af31-3baca4b1076e'})
SET p_si1_7.ProgrammCode = '38.5'
SET p_si1_7.ProgrammName = 'Бухгалтер'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_7)
MERGE (p_si1_7)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_8:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:8:c6ad4091-b264-a1e7-f124-040a6b07eca4'})
SET p_si1_8.ProgrammCode = '34.2'
SET p_si1_8.ProgrammName = 'Повар, кондитер'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_8)
MERGE (p_si1_8)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_9:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:9:a3aa5c9f-98a5-923d-d6b2-69032750e349'})
SET p_si1_9.ProgrammCode = '2.17'
SET p_si1_9.ProgrammName = 'Слесарь'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_9)
MERGE (p_si1_9)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_10:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:10:fe976b58-840f-fdb6-4ced-260793c2de8f'})
SET p_si1_10.UGSCode = '190000'
SET p_si1_10.UGSName = 'Транспортные средства'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_10)
MERGE (p_si1_10)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_11:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:11:7524243e-c581-784a-0345-b288c215cdda'})
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_11)
MERGE (elv2:EducationalLevel {uri: 'urn:accred:v1:EducationalLevel:b4c4325834193a43cf182fd00a6170b4175bb1f681bd23c9ba5aec1ae2a5b401'})
SET elv2.name = 'Профессиональная подготовка'
MERGE (p_si1_11)-[:HAS_EDUCATION_LEVEL]->(elv2)
MERGE (p_si1_12:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:12:48816ab7-4e68-bc7a-c506-1dacdd6ae0c9'})
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_12)
MERGE (p_si1_13:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:13:53c114a4-b5b9-dbdd-ba21-856bd6301ca6'})
SET p_si1_13.UGSCode = '160000'
SET p_si1_13.UGSName = 'Авиационная и ракетно-космическая техника'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_13)
MERGE (p_si1_13)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_14:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:14:5466ce66-2b3e-bb72-31fd-ce7156cce88e'})
SET p_si1_14.UGSCode = '34.00.00'
SET p_si1_14.UGSName = 'Сестринское дело'
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_14)
MERGE (p_si1_14)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si1_15:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:804817:15:00552064-1f0d-fa0c-33d1-519da9f7a9ab'})
MERGE (s1)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si1_15)
MERGE (p_si1_15)-[:HAS_EDUCATION_LEVEL]->(elv1)
MERGE (a_si1:ActualEducationOrganization {uri: 'urn:accred:v1:AEO:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:supplement:77733933-0fe3-d64b-b4bb-ce2c9a66f4ab'})
SET a_si1.Email = 'nspu@bk.ru'
SET a_si1.Fax = '34345-33606'
SET a_si1.FullName = 'государственное бюджетное образовательное учреждение начального профессионального образования Свердловской области "Нижнесалдинское профессиональное училище"'
SET a_si1.HeadName = 'Хрулькова Надежда Ивановна'
SET a_si1.HeadPost = 'Директор'
SET a_si1.INN = '6622002460'
SET a_si1.KPP = '662201001'
SET a_si1.OGRN = '1026600786783'
SET a_si1.Phone = '34345-33606'
SET a_si1.PostAddress = '624610 г.Нижняя Салда, ул.Парижской Коммуны, 1, 2'
SET a_si1.RegionName = 'Свердловская область'
SET a_si1.ShortName = 'ГБОУ НПО СО "НСПУ"'
MERGE (s1)-[:HAS_ACTUAL_EDUCATION_ORGANIZATION]->(a_si1)
MERGE (a_si1)-[:OFFERS_EDUCATION_LEVEL]->(elv1)
MERGE (a_si1)-[:OFFERS_EDUCATION_LEVEL]->(elv2)
MERGE (a_si1)-[:OFFERS_EDUCATION_LEVEL]->(elv0)
MERGE (a0:ActualEducationOrganization {uri: 'urn:accred:v1:AEO:data-20260403-structure-20160713.xml:2f13cd7a-530e-57ab-d71f-9482ee362cba:certificate:77733933-0fe3-d64b-b4bb-ce2c9a66f4ab'})
SET a0.Email = 'nspu@bk.ru'
SET a0.Fax = '34345-33606'
SET a0.FullName = 'государственное бюджетное образовательное учреждение начального профессионального образования Свердловской области "Нижнесалдинское профессиональное училище"'
SET a0.HeadName = 'Хрулькова Надежда Ивановна'
SET a0.HeadPost = 'Директор'
SET a0.INN = '6622002460'
SET a0.KPP = '662201001'
SET a0.OGRN = '1026600786783'
SET a0.Phone = '34345-33606'
SET a0.PostAddress = '624610 г.Нижняя Салда, ул.Парижской Коммуны, 1, 2'
SET a0.RegionName = 'Свердловская область'
SET a0.ShortName = 'ГБОУ НПО СО "НСПУ"'
MERGE (c)-[:HAS_ACTUAL_EDUCATION_ORGANIZATION]->(a0)
MERGE (a0)-[:OFFERS_EDUCATION_LEVEL]->(elv1)
MERGE (a0)-[:OFFERS_EDUCATION_LEVEL]->(elv2)
MERGE (a0)-[:OFFERS_EDUCATION_LEVEL]->(elv0);

