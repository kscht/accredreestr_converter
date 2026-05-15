// ВНИМАНИЕ: следующая команда удаляет все узлы и связи в активной базе Neo4j.
MATCH (n) DETACH DELETE n;

// Generated from JSONL by cypher_convert.export_cypher
// Labels match specs/kg/mapping.json node_kinds.kind
// Each certificate block ends with ';' for multi-statement clients (Neo4j Browser).

// --- certificate line 1 ---
MERGE (c:Certificate {uri: 'urn:accred:v1:Certificate:0000a217-d5f2-5067-113a-ebe576e4eaf0'})
SET c.ControlOrgan = 'Департамент образования Орловской области'
SET c.EduOrgFullName = 'муниципальное бюджетное общеобразовательное учреждение «Новоселовская основная общеобразовательная школа» Орловского муниципального округа Орловской области'
SET c.EduOrgINN = '5720010403'
SET c.EduOrgKPP = '572001001'
SET c.EduOrgOGRN = '1025700696383'
SET c.EduOrgShortName = 'МБОУ «Новоселовская ООШ» Орловского муниципального округа'
SET c.IsFederal = false
SET c.IssueDate = '2022-04-08'
SET c.PostAddress = '302532, Орловская область, Орловский муниципальный округ, д. Новосёлово, зд. 18'
SET c.RegNumber = 'А007-01229-57/01147030'
SET c.RegionCode = '57'
SET c.StatusName = 'Действующее'
MERGE (rg0:Region {uri: 'urn:accred:v1:Region:a9ee45910ce09190e8adfab42ed9a7757c5ead5da3b78f22b73865b68d37960f'})
SET rg0.name = 'Орловская область'
MERGE (c)-[:IN_REGION]->(rg0)
MERGE (s0:Supplement {uri: 'urn:accred:v1:Supplement:0000a217-d5f2-5067-113a-ebe576e4eaf0:769805'})
SET s0.EduOrgAddress = '302532, Орловская область, Орловский муниципальный округ, д. Новосёлово, зд. 18'
SET s0.EduOrgFullName = 'муниципальное бюджетное общеобразовательное учреждение «Новоселовская основная общеобразовательная школа» Орловского муниципального округа Орловской области'
SET s0.EduOrgKPP = '572001001'
SET s0.EduOrgShortName = 'МБОУ «Новоселовская ООШ» Орловского муниципального округа'
SET s0.FormNumber = '0000578'
SET s0.IssueDate = '2022-04-08'
SET s0.Number = '1'
SET s0.SerialNumber = '57А01'
SET s0.StatusName = 'Действующее'
MERGE (c)-[:HAS_SUPPLEMENT]->(s0)
MERGE (p_si0_0:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:0000a217-d5f2-5067-113a-ebe576e4eaf0:769805:0:ca453cc7-efa2-ccb9-20a2-0bfdc5d7712e'})
MERGE (s0)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si0_0)
MERGE (elv0:EducationalLevel {uri: 'urn:accred:v1:EducationalLevel:0cc2bf2195fdd59179c097eeb2e5205767e1ac3d36cfdf6003b22ced28ee5ae2'})
SET elv0.name = 'Основное общее образование'
MERGE (p_si0_0)-[:HAS_EDUCATION_LEVEL]->(elv0)
MERGE (p_si0_1:EducationalProgram {uri: 'urn:accred:v1:EducationalProgram:0000a217-d5f2-5067-113a-ebe576e4eaf0:769805:1:dcf39226-94f9-b867-02ce-2dc0341aabfa'})
MERGE (s0)-[:HAS_EDUCATIONAL_PROGRAM]->(p_si0_1)
MERGE (elv1:EducationalLevel {uri: 'urn:accred:v1:EducationalLevel:3f0803a4b1f9d62e6c7b3afc42040416d5291233e95fbb398b81a3d6bbdd21f7'})
SET elv1.name = 'Начальное общее образование'
MERGE (p_si0_1)-[:HAS_EDUCATION_LEVEL]->(elv1)
MERGE (a_si0:ActualEducationOrganization {uri: 'urn:accred:v1:AEO:0000a217-d5f2-5067-113a-ebe576e4eaf0:supplement:6d2bc866-607e-1b73-79d6-8487d3d90ae9'})
SET a_si0.Email = 'orlr_noosh@orel-region.ru'
SET a_si0.Fax = '+7 (4862) 40-48-24'
SET a_si0.FullName = 'муниципальное бюджетное общеобразовательное учреждение «Новоселовская основная общеобразовательная школа» Орловского муниципального округа Орловской области'
SET a_si0.HeadName = 'Зайцев Владимир Валерьевич'
SET a_si0.HeadPost = 'Директор'
SET a_si0.INN = '5720010403'
SET a_si0.KPP = '572001001'
SET a_si0.OGRN = '1025700696383'
SET a_si0.Phone = '+7 (4862) 40-48-24'
SET a_si0.PostAddress = '302532, Орловская область, Орловский муниципальный округ, д. Новосёлово, зд. 18'
SET a_si0.ShortName = 'МБОУ «Новоселовская ООШ» Орловского муниципального округа'
SET a_si0.WebSite = 'http://novoselovo.ucoz.ru/'
MERGE (a_si0)-[:IN_REGION]->(rg0)
MERGE (s0)-[:HAS_ACTUAL_EDUCATION_ORGANIZATION]->(a_si0)
MERGE (a_si0)-[:OFFERS_EDUCATION_LEVEL]->(elv1)
MERGE (a_si0)-[:OFFERS_EDUCATION_LEVEL]->(elv0)
MERGE (a0:ActualEducationOrganization {uri: 'urn:accred:v1:AEO:0000a217-d5f2-5067-113a-ebe576e4eaf0:certificate:6d2bc866-607e-1b73-79d6-8487d3d90ae9'})
SET a0.Email = 'orlr_noosh@orel-region.ru'
SET a0.Fax = '+7 (4862) 40-48-24'
SET a0.FullName = 'муниципальное бюджетное общеобразовательное учреждение «Новоселовская основная общеобразовательная школа» Орловского муниципального округа Орловской области'
SET a0.HeadName = 'Зайцев Владимир Валерьевич'
SET a0.HeadPost = 'Директор'
SET a0.INN = '5720010403'
SET a0.KPP = '572001001'
SET a0.OGRN = '1025700696383'
SET a0.Phone = '+7 (4862) 40-48-24'
SET a0.PostAddress = '302532, Орловская область, Орловский муниципальный округ, д. Новосёлово, зд. 18'
SET a0.ShortName = 'МБОУ «Новоселовская ООШ» Орловского муниципального округа'
SET a0.WebSite = 'http://novoselovo.ucoz.ru/'
MERGE (a0)-[:IN_REGION]->(rg0)
MERGE (c)-[:HAS_ACTUAL_EDUCATION_ORGANIZATION]->(a0)
MERGE (a0)-[:OFFERS_EDUCATION_LEVEL]->(elv1)
MERGE (a0)-[:OFFERS_EDUCATION_LEVEL]->(elv0);

