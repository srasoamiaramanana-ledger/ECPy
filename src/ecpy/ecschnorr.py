# Copyright 2016 Cedric Mesnil <cedric.mesnil@ubinity.com>, Ubinity SAS
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#python 2 compatibility
from builtins import int,pow

from ecpy.curves     import Curve,Point
from ecpy.keys       import ECPublicKey, ECPrivateKey
from ecpy.formatters import decode_sig, encode_sig, list_formats
from ecpy            import ecrand
from ecpy.curves     import ECPyException

import hashlib

class ECSchnorr:
    """ ECSchnorr signer implementation according to:
 
     - `BSI:TR03111 <https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Publications/TechGuidelines/TR03111/BSI-TR-03111_pdf.html>`_
     - `ISO/IEC:14888-3 <http://www.iso.org/iso/iso_catalogue/catalogue_ics/catalogue_detail_ics.htm?csnumber=43656>`_
     - `bitcoin-core:libsecp256k1 <https://github.com/bitcoin-core/secp256k1/blob/master/src/modules/schnorr/schnorr_impl.h>`_

    In order to select the specification to be conform to, choose 
    the corresponding string option:
 
    - "BSI": compute r,s according to to BSI : 
        - r = H(M||Q.x%n)
        - s = k - r.d
    - "ISO": compute r,s according to ISO : 
        - r = H(Q.x||Q.y||M)
        - s = k + r.d
    - "ISOx": compute r,s according to optimized ISO variant: 
        - r = H(Q.x||M)
        - s = k + r.d
    - "LIBSECP": compute r,s according to bitcoin lib: 
        - r = Q.x
        - h = Hash(r || m).
        - s = k - h * d.
       
    Default is "ISO"
    
    Args:
      hasher (hashlib): callable constructor returning an object with update(), digest() interface. Example: hashlib.sha256,  hashlib.sha512...
      option (int) : one of "BSI","ISO","ISOx","LIBSECP"
    """
    
    def __init__(self, hasher, option="ISO", fmt="DER"):
        if not option in ("ISO","ISOx","BSI","LIBSECP"):
            raise ECPyException('ECSchnorr option not supported: %s'%option)
        if not fmt in list_formats():
            raise ECPyException('ECSchnorr format not supported: %s'%fmt)

        self._hasher = hasher
        self.fmt = fmt
        self.maxtries=10
        self.option = option
        
    def sign(self, msg, pv_key):
        """ Signs a message hash.

        Args:
            hash_msg (bytes) : the hash of message to sign
            pv_key (ecpy.keys.PrivateKey): key to use for signing
        """
        order = pv_key.curve.order
        for i in range(1,self.maxtries):
            k = ecrand.rnd(order)
            sig = self._do_sign(msg, pv_key,k)
            if sig:
                return sig
        return None

    def sign_k(self, msg, pv_key, k):
        """ Signs a message hash  with provided random

        Args:
            hash_msg (bytes) : the hash of message to sign
            pv_key (ecpy.keys.PrivateKey): key to use for signing
            k (ecpy.keys.PrivateKey): random to use for signing
        """
        return self._do_sign(msg, pv_key,k)
            
    def _do_sign(self, msg, pv_key, k):
        if (pv_key.curve == None):
            raise ECPyException('private key haz no curve')
        curve = pv_key.curve
        n     = curve.order
        G     = curve.generator
        size  = curve.size>>3
        
        Q = G*k
        hasher = self._hasher()
        if self.option == "ISO":
            xQ = (Q.x).to_bytes(size,'big')        
            yQ = (Q.y).to_bytes(size,'big')
            hasher.update(xQ+yQ+msg)
            r = hasher.digest()
            r = int.from_bytes(r,'big')
            r = r%n        
            s = (k+r*pv_key.d)%n
            if r==0 or s==0:
                return None

        elif self.option == "ISOx":
            xQ = (Q.x).to_bytes(size,'big') 
            hasher.update(xQ+msg)
            r = hasher.digest()
            r = int.from_bytes(r,'big')
            r = r%n        
            s = (k+r*pv_key.d)%n
            if r==0 or s==0:
                return None
            
        elif self.option == "BSI":
            xQ = (Q.x%n).to_bytes(size,'big') 
            hasher.update(msg+xQ)
            r = hasher.digest()
            r = int.from_bytes(r,'big')
            r = r%n
            s = (k-r*pv_key.d)%n
            if r==0 or s==0:
                return None

        elif self.option == "LIBSECP":
            if Q.y & 1:
                k = n-k
                Q = G*k
            r = Q.x.to_bytes(size,'big')
            hasher.update(r+msg)
            h = hasher.digest()
            h = int.from_bytes(h,'big')
            if h == 0 or h>n:
                return None
            r = Q.x
            s = (k - h*pv_key.d)%n
        
        return encode_sig(r, s, self.fmt)
            
    def verify(self,msg,sig,pu_key):
        """ Verifies a message signature.                

        Args:
            hash_msg (bytes)      : the hash of message to verify the signature
            sig (bytes)           : signature to verify
            pu_key (key.PublicKey): key to use for verifying
        """
        curve = pu_key.curve
        n     = pu_key.curve.order
        G     = pu_key.curve.generator
        size  = curve.size>>3
        
        r,s = decode_sig(sig, self.fmt)
        if (r == None             or
            r > (pow(2,size*8)-1) or
            s == 0                or
            s > n-1     ) :
            return False

        hasher = self._hasher()
        if self.option == "ISO":
            Q =  s*G - r*pu_key.W
            xQ = Q.x.to_bytes(size,'big')
            yQ = Q.y.to_bytes(size,'big')
            hasher.update(xQ+yQ+msg)
            v = hasher.digest()
            v = int.from_bytes(v,'big')
            v = v%n
        
        elif self.option == "ISOx":
            Q =  s*G - r*pu_key.W
            xQ = Q.x.to_bytes(size,'big')
            hasher.update(xQ+msg)
            v = hasher.digest()
            v = int.from_bytes(v,'big')
            v = v%n

        elif self.option == "BSI":
            Q =  s*G + r*pu_key.W
            xQ = (Q.x%n).to_bytes(size,'big')
            hasher.update(msg+xQ)
            v = hasher.digest()
            v = int.from_bytes(v,'big')
            v = v%n

        elif self.option == "LIBSECP":
            rb = r.to_bytes(size,'big') 
            hasher.update(rb+msg)
            h = hasher.digest()
            h = int.from_bytes(h,'big')
            R = s * G + h*pu_key.W
            v = R.x % n
        
        return v == r
 
if __name__ == "__main__":
    import sys
    try:
        cv     = Curve.get_curve('NIST-P256')
        pu_key = ECPublicKey(Point(0x09b58b88323c52d1080aa525c89e8e12c6f40fcb014640fa88081ed9e9352de7,
                                   0x5ccbbd189538516238b0b0b28acb5f0b5e27217c3a9872421219de0aeebf1080,
                                   cv))
        pv_key = ECPrivateKey(0x5202a3d8acaf6909d12c9a774cd886f9fba61137ffd3e8e76aed363fb47ac492,
                              cv)

        msg = int(0x616263)
        msg  = msg.to_bytes(3,'big')

        k = int(0xde7e0e5e663f24183414b7c72f24546b81e9e5f410bebf26f3ca5fa82f5192c8)

        ## ISO
        R=0x5A79A0AA9B241E381A594B220554D096A5F09FA628AD9A33C3CE4393ADE1DEF7
        S=0x5C0EB78B67A513C3E53B2619F96855E291D5141C7CD0915E1D04B347457C9601

        signer = ECSchnorr(hashlib.sha256,"ISO","ITUPLE")
        sig = signer.sign_k(msg,pv_key,k)
        assert(R==sig[0])
        assert(S==sig[1])
        assert(signer.verify(msg,sig,pu_key))
        
        ##ISOx
        R = 0xd7fb8135d8ea45e8fb3c9059f146e2630ef4bd51c4006a92edb4c8b0849963fb
        S = 0xb46d1525379e02e232d97928265b7254ea2ed97813454388c1a08f62dccd70b3

        signer = ECSchnorr(hashlib.sha256,"ISOx","ITUPLE")
        sig = signer.sign_k(msg,pv_key,k)
        assert(R==sig[0])
        assert(S==sig[1])
        assert(signer.verify(msg,sig,pu_key))

        ##BSI
        signer = ECSchnorr(hashlib.sha256,"BSI","ITUPLE")
        sig = signer.sign_k(msg,pv_key,k)
        assert(signer.verify(msg,sig,pu_key))

        ##LIBSECP
        signer = ECSchnorr(hashlib.sha256,"LIBSECP","ITUPLE")
        sig = signer.sign_k(msg,pv_key,k)
        assert(signer.verify(msg,sig,pu_key))
        
        # ##OK!
        print("All internal assert OK!")
    finally:
        pass
