'use strict';

const HOLDER_REFUSAL_CODES = ['ADOPTION_REFUSED', 'PORT_HOLDER_NOT_YOURS', 'PORT_HOLDER_NOT_CARNIVORE'];

function isForeignHolderRefusal(err) {
  return Boolean(err) && HOLDER_REFUSAL_CODES.includes(err.code);
}

module.exports = { HOLDER_REFUSAL_CODES, isForeignHolderRefusal };
