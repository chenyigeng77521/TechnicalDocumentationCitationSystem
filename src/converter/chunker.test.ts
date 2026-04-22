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

test('md: short section becomes single chunk with prepended heading', () => {
  const mdContent = '# Section A\n\nShort body.';
  const result = chunkDocument({
    fileId: 'f1', format: 'md', mdContent, lineMappings: []
  });
  assert.strictEqual(result.length, 1);
  assert.ok(result[0].content.startsWith('# Section A'));
  assert.ok(result[0].content.includes('Short body.'));
});

test('md: section >800 chars is split; each sub-chunk prepends heading', () => {
  const para = 'x'.repeat(400);
  const mdContent = `# Big\n\n${para}\n\n${para}\n\n${para}`;
  const result = chunkDocument({
    fileId: 'f1', format: 'md', mdContent, lineMappings: []
  });
  assert.strictEqual(result.length, 3, `expected 3 chunks for 3x 400-char paragraphs, got ${result.length}`);
  for (const c of result) {
    assert.ok(c.content.startsWith('# Big'), 'each chunk should prepend heading');
  }
});

test('md: content before first heading is its own chunk without prepend', () => {
  const mdContent = 'Intro text.\n\n# Later\n\nBody.';
  const result = chunkDocument({
    fileId: 'f1', format: 'md', mdContent, lineMappings: []
  });
  const intro = result.find(c => c.content.includes('Intro text.'));
  assert.ok(intro, 'intro chunk should exist');
  assert.ok(!intro!.content.startsWith('#'), 'intro chunk has empty section');
});

test('md: original_lines maps via lineMappings, not shifted by prepend', () => {
  const mdContent = '# Title\n\nBody line.';
  const lineMappings = [
    { mdLine: 1, originalLine: 100, content: '# Title', context: '' },
    { mdLine: 3, originalLine: 102, content: 'Body line.', context: '' }
  ];
  const result = chunkDocument({
    fileId: 'f1', format: 'md', mdContent, lineMappings
  });
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].start_line, 1);
  assert.strictEqual(result[0].end_line, 3);
  assert.deepStrictEqual(result[0].original_lines, [100, 102]);
});

test('md: multiple sections produce multiple chunks', () => {
  const mdContent = '# A\n\nbody A\n\n# B\n\nbody B';
  const result = chunkDocument({
    fileId: 'f1', format: 'md', mdContent, lineMappings: []
  });
  assert.strictEqual(result.length, 2);
  assert.ok(result[0].content.includes('body A'));
  assert.ok(result[1].content.includes('body B'));
});

test('md: single giant paragraph with no blank lines is force-split at 2000 chars', () => {
  const giant = 'a'.repeat(5000);  // > 2000, no blank lines
  const mdContent = `# Big\n\n${giant}`;
  const result = chunkDocument({
    fileId: 'f1', format: 'md', mdContent, lineMappings: []
  });
  // Expect 3 chunks (ceil(5000/2000) = 3), each prepending heading
  assert.strictEqual(result.length, 3);
  for (const c of result) {
    assert.ok(c.content.startsWith('# Big'), 'each chunk should prepend heading');
    // Content length = heading(5) + "\n\n"(2) + slice(≤2000) = ≤2007
    assert.ok(c.content.length <= 2010, `chunk too long: ${c.content.length}`);
  }
});

test('xlsx: groups 20 data rows per chunk, prepends sheet + header', () => {
  const rows = Array.from({ length: 25 }, (_, i) => `| v${i} | ${i} |`).join('\n');
  const mdContent = `## Sheet1\n\n| 列 | 数据 |\n|----|------|\n${rows}\n`;
  const result = chunkDocument({
    fileId: 'f1', format: 'xlsx', mdContent, lineMappings: []
  });
  assert.strictEqual(result.length, 2, `expected 2 chunks for 25 rows, got ${result.length}`);
  assert.ok(result[0].content.startsWith('## Sheet1'));
  assert.ok(result[0].content.includes('| 列 | 数据 |'));
  assert.strictEqual(
    (result[0].content.match(/\| v\d+ \|/g) || []).length,
    20,
    'first chunk should have 20 data rows'
  );
  assert.strictEqual(
    (result[1].content.match(/\| v\d+ \|/g) || []).length,
    5,
    'second chunk should have 5 data rows'
  );
});

test('xlsx: multiple sheets produce separate chunks', () => {
  const mdContent = `## Sheet1\n\n| 列 | 数据 |\n|----|------|\n| a | 1 |\n\n## Sheet2\n\n| 列 | 数据 |\n|----|------|\n| b | 2 |\n`;
  const result = chunkDocument({
    fileId: 'f1', format: 'xlsx', mdContent, lineMappings: []
  });
  assert.strictEqual(result.length, 2);
  assert.ok(result[0].content.startsWith('## Sheet1'));
  assert.ok(result[1].content.startsWith('## Sheet2'));
});

test('xlsx: prepended header does not count toward 20-row quota', () => {
  // 精确 20 行数据 → 应该只产出 1 个 chunk（不是 2 个）
  const rows = Array.from({ length: 20 }, (_, i) => `| v${i} | ${i} |`).join('\n');
  const mdContent = `## Sheet1\n\n| 列 | 数据 |\n|----|------|\n${rows}\n`;
  const result = chunkDocument({
    fileId: 'f1', format: 'xlsx', mdContent, lineMappings: []
  });
  assert.strictEqual(result.length, 1);
});
