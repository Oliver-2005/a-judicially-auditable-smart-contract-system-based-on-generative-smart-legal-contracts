const path = require('path');
require('@nomicfoundation/hardhat-toolbox');
const { subtask } = require('hardhat/config');
const { TASK_COMPILE_SOLIDITY_GET_SOLC_BUILD } = require('hardhat/builtin-tasks/task-names');
subtask(TASK_COMPILE_SOLIDITY_GET_SOLC_BUILD).setAction(async ({ solcVersion }, hre, runSuper) => {
  if (solcVersion !== '0.8.26') return runSuper();
  const solc = require('solc');
  if (!solc.version().startsWith('0.8.26+')) throw new Error('Expected solc 0.8.26');
  return { compilerPath: require.resolve('solc/soljson.js'), isSolcJs: true,
    version: '0.8.26', longVersion: solc.version() };
});
const build = process.env.SLCML_BUILD_DIR || path.join(__dirname, '.build');
module.exports = {
  solidity: { version: '0.8.26', settings: { optimizer: { enabled: true, runs: 200 }, viaIR: true, evmVersion: 'paris' } },
  networks: { hardhat: { chainId: 31337, initialDate: '2026-10-09T00:00:00Z' } },
  gasReporter: { enabled: false },
  paths: { root: __dirname, sources: path.join(__dirname, 'am/contracts'),
    tests: path.join(__dirname, 'am/test'), cache: path.join(build, 'am/cache'), artifacts: path.join(build, 'am/artifacts') },
  mocha: { timeout: 120000 }
};

