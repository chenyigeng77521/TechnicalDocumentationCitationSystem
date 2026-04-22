import { test } from 'node:test';
import assert from 'node:assert';
import { chunkDocument } from './chunker.js';

test('returns empty array for empty content', () => {
  const result = chunkDocument({
    fileId: 'f1',
    format: 'md',
    mdContent: '',
    lineMappings: []
  });
  assert.strictEqual(result.length, 0);
});

test('generates deterministic chunk IDs for same input', () => {
  const input = {
    fileId: 'f1',
    format: 'md' as const,
    mdContent: '# Title\n\nSome content.',
    lineMappings: []
  };
  const r1 = chunkDocument(input);
  const r2 = chunkDocument(input);
  assert.deepStrictEqual(r1.map(c => c.id), r2.map(c => c.id));
  assert.ok(r1.length > 0, 'should produce at least one chunk');
});

test('different fileId yields different chunk IDs', () => {
  const base = { format: 'md' as const, mdContent: '# A\n\nx', lineMappings: [] };
  const a = chunkDocument({ ...base, fileId: 'f1' });
  const b = chunkDocument({ ...base, fileId: 'f2' });
  assert.notStrictEqual(a[0].id, b[0].id);
});
