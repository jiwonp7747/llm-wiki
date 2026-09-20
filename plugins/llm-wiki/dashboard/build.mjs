import {build} from 'esbuild';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
await mkdir('dist', {recursive: true});
await build({entryPoints: ['src/app.jsx'], bundle: true, minify: true, outfile: 'dist/app.js',
  loader: {'.woff': 'file', '.woff2': 'file', '.ttf': 'file', '.eot': 'file', '.svg': 'file'},
  define: {'process.env.NODE_ENV': '"production"'}, legalComments: 'linked'});
await writeFile('dist/index.html', '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LLM Wiki · 사용 현황</title><link rel="stylesheet" href="/assets/app.css"></head><body><div id="root"></div><script src="/assets/app.js" defer></script></body></html>');

const licensePath = 'dist/app.js.LEGAL.txt';
await writeFile(licensePath, (await readFile(licensePath, 'utf8')).replace(/\t/g, '  '));
