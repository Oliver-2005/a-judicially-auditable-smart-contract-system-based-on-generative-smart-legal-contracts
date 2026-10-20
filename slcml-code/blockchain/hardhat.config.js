const path = require('path');
require('@nomicfoundation/hardhat-toolbox');
const build = process.env.SLCML_BUILD_DIR || path.join(__dirname, '.build');
module.exports = {
  solidity: { version: '0.8.20', settings: { optimizer: { enabled: true, runs: 200 }, viaIR: true } },
  networks: { hardhat: { chainId: 31337, mining: { auto: true, interval: 0 },
    accounts: { count: 10, initialBalance: '10000000000000000000000' } } },
  gasReporter: { enabled: false },
  paths: { root: __dirname, sources: path.join(__dirname, 'main/contracts'),
    tests: path.join(__dirname, 'main/test'), cache: path.join(build, 'main/cache'), artifacts: path.join(build, 'main/artifacts') },
  mocha: { timeout: 120000 }
};

