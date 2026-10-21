#!/usr/bin/env node
/**
 * Small, dependency-free helper shared by apply.sh / rollback.sh (and the .bat pair).
 *
 * Commands:
 *   show     <packageJsonPath>            print the declared spec of dsh-better-sidebar
 *   pin      <packageJsonPath> <version>  set that one dependency to an exact version
 *   resolved <profileDir>                 print the version dsh-better-sidebar resolves to
 *   nested   <profileDir>                 print the aggregate bundle's own nested copy version
 *
 * Every command prints a one-line result on stdout and exits 0 on success.
 * `pin` refuses to write if anything other than the target dependency would change.
 */
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')

const PKG = 'dsh-better-sidebar'
const AGGREGATE = '@linxin666/dsh-web-ui-all'

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'))
}

function formatJson(value) {
  // The profile's package.json is authored with 2-space indentation and a final newline.
  return JSON.stringify(value, null, 2) + '\n'
}

function show(packageJsonPath) {
  const manifest = readJson(packageJsonPath)
  const spec = manifest.dependencies && manifest.dependencies[PKG]
  if (typeof spec !== 'string') {
    console.error(`[tools] ${packageJsonPath} does not declare ${PKG}`)
    process.exit(2)
  }
  process.stdout.write(spec + '\n')
}

function pin(packageJsonPath, version) {
  if (!/^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/.test(version)) {
    console.error(`[tools] refusing non-exact version: ${version}`)
    process.exit(2)
  }
  const before = readJson(packageJsonPath)
  if (!before.dependencies || typeof before.dependencies[PKG] !== 'string') {
    console.error(`[tools] ${packageJsonPath} does not declare ${PKG}`)
    process.exit(2)
  }

  const after = JSON.parse(JSON.stringify(before))
  after.dependencies[PKG] = version

  // Safety: prove the ONLY difference is that single dependency value.
  const changed = []
  const topKeys = new Set([...Object.keys(before), ...Object.keys(after)])
  for (const key of topKeys) {
    if (JSON.stringify(before[key]) === JSON.stringify(after[key])) continue
    if (key === 'dependencies') {
      const depKeys = new Set([
        ...Object.keys(before.dependencies || {}),
        ...Object.keys(after.dependencies || {}),
      ])
      for (const dep of depKeys) {
        if (before.dependencies[dep] !== after.dependencies[dep]) changed.push(`dependencies.${dep}`)
      }
      continue
    }
    changed.push(key)
  }

  if (changed.length !== 1 || changed[0] !== `dependencies.${PKG}`) {
    console.error(`[tools] unexpected diff, aborting: ${changed.join(', ')}`)
    process.exit(3)
  }

  const rendered = formatJson(after)
  // Preserve the original file if it was already exactly this content.
  if (rendered === fs.readFileSync(packageJsonPath, 'utf8')) {
    process.stdout.write(`unchanged ${PKG}@${version}\n`)
    return
  }
  fs.writeFileSync(packageJsonPath, rendered)
  process.stdout.write(`pinned ${PKG}: ${before.dependencies[PKG]} -> ${version}\n`)
}

function resolvedVersion(profileDir) {
  const requireFromProfile = createRequire(path.join(profileDir, 'package.json'))
  const manifestPath = requireFromProfile.resolve(`${PKG}/package.json`)
  return { version: readJson(manifestPath).version, manifestPath }
}

function resolved(profileDir) {
  try {
    const { version } = resolvedVersion(profileDir)
    process.stdout.write(version + '\n')
  } catch {
    process.stdout.write('UNRESOLVED\n')
  }
}

function nested(profileDir) {
  const nestedPath = path.join(profileDir, 'node_modules', AGGREGATE, 'node_modules', PKG, 'package.json')
  if (!fs.existsSync(nestedPath)) {
    process.stdout.write('none\n')
    return
  }
  process.stdout.write(readJson(nestedPath).version + '\n')
}

function main(argv) {
  const [command, ...args] = argv
  switch (command) {
    case 'show':
      return show(args[0])
    case 'pin':
      return pin(args[0], args[1])
    case 'resolved':
      return resolved(args[0])
    case 'nested':
      return nested(args[0])
    default:
      console.error('usage: tools.cjs show|pin|resolved|nested ...')
      process.exit(2)
  }
}

main(process.argv.slice(2))
