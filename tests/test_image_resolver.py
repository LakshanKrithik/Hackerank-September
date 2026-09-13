import unittest
import os
from code.data_loader import DataLoader
from code.image_resolver import ImageResolver, EXTRACTED_IMAGE_AMOUNTS


class TestImageResolver(unittest.TestCase):
    def setUp(self):
        self.dataset_exists = os.path.exists('dataset')
        if self.dataset_exists:
            self.loader = DataLoader('dataset')
            self.resolver = ImageResolver(self.loader)
        else:
            self.loader = None
            self.resolver = ImageResolver(None)

    def test_all_16_images_mapped(self):
        all_resolved = self.resolver.resolve_all_images()
        self.assertEqual(len(all_resolved), 16)
        if self.dataset_exists:
            images_df = self.loader.df_images
            self.assertEqual(len(images_df), 16)
            for _, row in images_df.iterrows():
                eid = row['related_event_id']
                self.assertIn(eid, all_resolved)
                self.assertGreater(all_resolved[eid], 0.0)

    def test_sample_image_amounts(self):
        # image_01 -> event_253: 4,365,000 IDR
        self.assertEqual(self.resolver.get_event_amount('event_253'), 4365000.0)
        # image_02 -> event_1442: 100,000 INR
        self.assertEqual(self.resolver.get_event_amount('event_1442'), 100000.0)
        # image_16 -> event_10521: 393.22 INR
        self.assertEqual(self.resolver.get_event_amount('event_10521'), 393.22)


if __name__ == '__main__':
    unittest.main()
