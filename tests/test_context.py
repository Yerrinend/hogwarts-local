import copy
import json
from pathlib import Path
import unittest
from context_pack import build,decode_text

class ContextTests(unittest.TestCase):
    def test_russian_utf8_bom_and_cp1251(self):
        text='Персонажи и мир: Драка, Элли, Мэри.'
        self.assertEqual(decode_text(text.encode('utf-8-sig')),(text,'UTF-8'))
        self.assertEqual(decode_text(text.encode('cp1251')),(text,'Windows-1251'))
        with self.assertRaises(ValueError):decode_text(b'\0binary')

    def test_large_sources_retrieve_relevant_sections_without_mutating(self):
        s={'hero':'Иван','memory':'Занятие зельями. Снейп.','chapters':[],'files':{
            'правила.md':'# Правила\nСохраняй свободу героя.',
            'Снейп.md':'# Зелья\nСнейп говорит тихо.\n'+'x '*90000,
            'другое.md':'# Другое\n'+'y '*90000}}
        before=copy.deepcopy(s)
        packet=json.loads(build(s,'Снейп зелья'))
        self.assertIn('правила.md',packet['world_excerpts'])
        self.assertIn('Снейп.md',packet['world_excerpts'])
        self.assertTrue(packet['retrieval']['partly_included'])
        self.assertEqual(s,before)
        self.assertLessEqual(len(build(s)),180000)

    def test_world_pack_has_no_personal_start_state(self):
        pack=json.loads((Path(__file__).resolve().parents[1]/'starter/game.json').read_text(encoding='utf-8'))
        self.assertEqual(pack['version'],'1.2')
        self.assertEqual(len([p for p in pack['files'] if p.startswith('gm_year_')]),7)
        start=pack['files']['quick_save.md']
        self.assertNotIn('21.12.1991',start)
        self.assertIn('1973',pack['files']['world.md'])
        self.assertNotIn('Школьные персонажи несовершеннолетние',pack['instructions'])
        self.assertFalse(any('full_chapters' in name for name in pack['files']))

if __name__=='__main__':unittest.main()
