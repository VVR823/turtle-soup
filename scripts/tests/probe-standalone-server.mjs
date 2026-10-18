/** Test-only ownership/EOF controls around the actual generated server.js. */
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import net from 'node:net';
import { createRequire } from 'node:module';

const [artifact, rawPort, instance] = process.argv.slice(2);
const port = Number(rawPort);
if (!artifact || !path.isAbsolute(artifact) || fs.realpathSync(artifact) !== artifact
  || !Number.isInteger(port) || port < 1024 || port > 65535 || !/^[0-9a-f-]{36}$/.test(instance || '')) {
  throw new Error('Explicit owned artifact identity required');
}
let outbound = 0;
net.Socket.prototype.connect = function () { outbound++; throw new Error('Outbound network forbidden in LOCAL artifact smoke'); };
const emit = http.Server.prototype.emit;
http.Server.prototype.emit = function (event, ...args) {
  if (event === 'request' && this.address()?.port === port) args[1].setHeader('X-TS17-Instance', instance);
  return emit.call(this, event, ...args);
};
const listen = http.Server.prototype.listen;
http.Server.prototype.listen = function (...args) {
  this.once('listening', () => {
    const address = this.address();
    if (address?.port !== port || address?.address !== '127.0.0.1') throw new Error('Unexpected artifact listener');
    console.log(`TS17_ARTIFACT_LISTENING:${instance}`);
  });
  return listen.apply(this, args);
};
function verifyOrigins() {
  const require = createRequire(import.meta.url);
  const loaded = Object.keys(require.cache).filter(name => name.includes(`${path.sep}node_modules${path.sep}`));
  if (!loaded.some(name => name.startsWith(path.join(artifact, 'node_modules/next') + path.sep))
    || loaded.some(name => {
      const relative = path.relative(artifact, name);
      return relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative);
    }) || outbound) throw new Error('Artifact dependency origin or offline boundary failed');
}
process.stdin.once('end', () => {
  try {
    verifyOrigins();
    if (!process.listenerCount('SIGTERM')) throw new Error('No actual graceful shutdown handler');
    console.log(`TS17_ARTIFACT_ORIGINS:${instance}`);
    console.log(`TS17_ARTIFACT_EOF:${instance}`);
    // Call Next's real cooperative cleanup, not Windows process termination.
    process.emit('SIGTERM', 'SIGTERM');
  } catch (error) { console.error(error.message); process.exitCode = 1; process.emit('SIGTERM', 'SIGTERM'); }
});
process.stdin.resume();
const require = createRequire(path.join(artifact, 'server.js'));
require(path.join(artifact, 'server.js'));
